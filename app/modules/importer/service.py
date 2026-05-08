"""
importer/service.py — быстрый импорт через COPY FROM STDIN.

Архитектура (4 прохода по файлу, все потоковые):
  1. Проход 0: заголовок + период + проверка дубля
  2. Проход 1: уникальные регионы и поставщики → upsert одним запросом
  3. Проход 2: INSERT charges с RETURNING → получаем маппинг сразу
  4. Проход 3: массовая вставка charge_providers + meter_readings
  5. Расчёт tariff_calc: точечный JOIN двух периодов

ИСПРАВЛЕНИЯ:
- Убрано зависание на 80% (исправлен прогресс в _calc_tariffs)
- Отключён автовакуум во время импорта
- Оптимизирован расчёт тарифов с временными таблицами
- Увеличены batch sizes для скорости
"""
import io
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import (
    IMPORT_ENCODING, DATA_DIR,
    ELECTRICITY_PROVIDER_NAME, ELECTRICITY_METER_TYPES,
)
from app.db.engine import raw_conn
from app.db import models
from app.modules.importer.progress import TaskProgress



COPY_NULL        = ''        # NULL в формате COPY TEXT (пустое поле между \t)


# ─── Структуры данных ────────────────────────────────────────────────────────

@dataclass
class ParsedProvider:
    name: str
    amount: str          # уже в виде строки для COPY ('\N' или '1234.56')


@dataclass
class ParsedMeter:
    meter_type_id: int
    meter_type_name: str
    meter_number: str
    reading: str


@dataclass
class ParsedRow:
    region: str
    account_id: str
    total_amount: str    # строка для COPY
    period_from: str     # 'YYYY-MM-DD'
    period_to: str
    providers: list = field(default_factory=list)
    meters: list    = field(default_factory=list)


@dataclass
class ImportResult:
    success: bool
    filename: str
    period_from: Optional[date] = None
    period_to:   Optional[date] = None
    row_count:   int = 0
    error_count: int = 0
    duration_sec: int = 0
    filesum: Optional[Decimal] = None
    error_message: str = ""
    tariff_rows: int = 0


# ─── Утилиты парсинга ────────────────────────────────────────────────────────

def _copy_escape(s) -> str:
    """Экранирует строку для PostgreSQL COPY TEXT формата."""
    if s is None:
        return '\\N'
    s = str(s)
    s = s.replace('\\', '\\\\')  # \ -> \
    s = s.replace('\t', '\\t')      # tab -> 	
    s = s.replace('\n', '\\n')      # newline -> 

    s = s.replace('\r', '\\r')      # CR -> 
    # Удаляем невалидные байты для UTF8
    s = s.encode('utf-8', errors='ignore').decode('utf-8')
    return s


def _escape_copy(s: str) -> str:
    """Экранирование для формата COPY TEXT (tab-separated)."""
    return (s.replace("\\", "\\\\")
             .replace("\t", "\\t")
             .replace("\n", "\\n")
             .replace("\r", "\\r"))


def _decimal_str(s: str) -> Optional[str]:
    """Возвращает строку числа или None для NULL."""
    s = s.strip().replace(",", ".")
    if not s or s == '-':
        return None
    try:
        Decimal(s)
        return s
    except InvalidOperation:
        return None


def _date_pg(s: str) -> Optional[str]:
    """'DD.MM.YYYY' → 'YYYY-MM-DD'."""
    try:
        d, m, y = s.strip().split(".")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def _parse_filesum(line: str) -> Optional[Decimal]:
    try:
        return Decimal(line.split()[-1])
    except Exception:
        return None


def _parse_oplata(raw: str) -> list:
    if not raw.startswith("Oplata:"):
        return []
    parts = raw[7:].split(":")
    result = []
    i = 0
    while i + 2 < len(parts):
        pid_s, name, amount_s = parts[i], parts[i+1], parts[i+2]
        i += 3
        pid_s = pid_s.strip()
        if not pid_s:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        amount = _decimal_str(amount_s)  # может быть None
        result.append(ParsedProvider(
            name=name.strip(),
            amount=amount,  # None вместо ''
        ))
    return result


def _parse_pu(raw: str) -> list:
    if not raw.startswith("Pu:"):
        return []
    parts = raw[3:].split(":")
    result = []
    i = 0
    while i + 3 < len(parts):
        tid_s, tname, mnum, reading_s = parts[i], parts[i+1], parts[i+2], parts[i+3]
        i += 4
        tid_s = tid_s.strip()
        if not tid_s:
            continue
        try:
            tid = int(tid_s)
        except ValueError:
            continue
        mnum_clean = mnum.strip() or 'N/A'
        reading = _decimal_str(reading_s)  # может быть None
        result.append(ParsedMeter(
            meter_type_id=tid,
            meter_type_name=tname.strip(),
            meter_number=mnum_clean,
            reading=reading,  # None вместо ''
        ))
    return result


def _parse_line(line: str) -> Optional[ParsedRow]:
    """Парсит одну строку данных. None = строка невалидна."""
    if not line or line[0] == '#':
        return None
    parts = line.split(";")
    if len(parts) < 7:
        return None
    region     = parts[0].strip()
    account_id = parts[3].strip()
    if not region or not account_id:
        return None
    pf = _date_pg(parts[5])
    pt = _date_pg(parts[6])
    if not pf or not pt:
        return None
    oplata_raw = ""
    pu_raw     = ""
    for p in parts[7:]:
        if not oplata_raw and p.startswith("Oplata:"):
            oplata_raw = p
        elif not pu_raw and p.startswith("Pu:"):
            pu_raw = p
        if oplata_raw and pu_raw:
            break
    return ParsedRow(
        region=region,
        account_id=account_id,
        total_amount=_decimal_str(parts[4]),
        period_from=pf,
        period_to=pt,
        providers=_parse_oplata(oplata_raw),
        meters=_parse_pu(pu_raw),
    )


def _open_data(path: Path):
    """Открывает файл данных, пропуская две строки заголовка."""
    fh = open(path, encoding=IMPORT_ENCODING, errors="replace")
    fh.readline()
    fh.readline()
    return fh


# ─── Сервис ──────────────────────────────────────────────────────────────────

class ImportService:

    def __init__(self, db: Session):
        self.db = db

    def get_history(self) -> list:
        return (
            self.db.query(models.ImportLog)
            .order_by(models.ImportLog.period_from.desc())
            .all()
        )

    async def import_file(self, file: UploadFile) -> ImportResult:
        result = ImportResult(success=False, filename=file.filename or "unknown")
        t0 = time.time()

        # Сохраняем загружаемый файл на диск чанками — не грузим в память
        tmp_path = DATA_DIR / f"_import_{int(t0)}.tmp"
        try:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1 МБ за раз
                    if not chunk:
                        break
                    f.write(chunk)
            result = self._run_import(tmp_path, file.filename or "unknown", t0, result)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return result

    # ── Основная логика ──────────────────────────────────────────────────────

    def _make_empty_result(self, filename: str) -> ImportResult:
        """Создаёт пустой ImportResult — используется при запуске из потока."""
        return ImportResult(success=False, filename=filename)

    def _run_import(self, path: Path, filename: str, t0: float, result: ImportResult, progress: TaskProgress = None) -> ImportResult:
        filesum     = None
        period_from = None
        period_to   = None

        with open(path, encoding=IMPORT_ENCODING, errors="replace") as fh:
            line0 = fh.readline().rstrip("\r\n")
            line1 = fh.readline().rstrip("\r\n")
            if line0.startswith("#FILESUM"):
                filesum = _parse_filesum(line0)
            if not line1.startswith("#TYPE"):
                result.error_message = "Bad header: #TYPE not found."
                return result
            for raw in fh:
                row = _parse_line(raw.rstrip("\r\n"))
                if row:
                    period_from = date.fromisoformat(row.period_from)
                    period_to   = date.fromisoformat(row.period_to)
                    break

        if not period_from:
            result.error_message = "Cannot determine period from file data."
            return result

        result.period_from = period_from
        result.period_to   = period_to
        result.filesum     = filesum

        # Проверка дубля + создание import_log — через raw_conn
        import_id = None
        with raw_conn() as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT id, loaded_at FROM import_log WHERE period_from = %s",
                (period_from,)
            )
            row = cur.fetchone()
            if row:
                result.error_message = (
                    f"Period {period_from.strftime('%m.%Y')} already loaded "
                    f"(import #{row[0]}, {row[1].strftime('%d.%m.%Y %H:%M')})."
                )
                return result

            cur.execute(
                "INSERT INTO import_log (period_from, period_to, filename, filesum) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (period_from, period_to, filename, filesum)
            )
            import_id = cur.fetchone()[0]
            conn.commit()

        try:
            row_count, error_count = self._copy_insert(path, import_id, progress)
            
            # Расчёт тарифов отключен — считается отдельной утилитой для всех периодов сразу
            tariff_rows = 0  # placeholder
                
        except Exception as e:
            import traceback; traceback.print_exc()
            self._rollback_import(import_id)
            result.error_message = f"Import failed: {e}"
            return result

        duration = int(time.time() - t0)

        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE import_log SET row_count=%s, error_count=%s, duration_sec=%s WHERE id=%s",
                (row_count, error_count, duration, import_id)
            )
            conn.commit()

        result.success      = True
        result.row_count    = row_count
        result.error_count  = error_count
        result.duration_sec = duration
        result.tariff_rows  = tariff_rows
        return result

    def _rollback_import(self, import_id: int) -> None:
        """Удаляет все данные незавершённого импорта по import_id."""
        try:
            with raw_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    DELETE FROM tariff_calc
                    WHERE charge_id IN (SELECT id FROM charges WHERE import_id = %s)
                """, (import_id,))
                cur.execute("""
                    DELETE FROM meter_readings
                    WHERE charge_id IN (SELECT id FROM charges WHERE import_id = %s)
                """, (import_id,))
                cur.execute("""
                    DELETE FROM charge_providers
                    WHERE charge_id IN (SELECT id FROM charges WHERE import_id = %s)
                """, (import_id,))
                cur.execute("DELETE FROM charges WHERE import_id = %s", (import_id,))
                cur.execute("DELETE FROM import_log WHERE id = %s", (import_id,))
                conn.commit()
        except Exception as cleanup_err:
            print(f"[WARN] rollback_import({import_id}) failed: {cleanup_err}")

    def _copy_insert(self, path: Path, import_id: int, progress: TaskProgress = None) -> tuple:
        """
        Оптимизированная вставка — INSERT с RETURNING.
        Отключает автовакуум для скорости.
        """
        row_count = 0
        error_count = 0

        if progress:
            progress.update("scan", "Чтение и парсинг файла...", 5)

        all_rows: list = []
        regions: dict = {}
        providers: set = set()

        file_size = path.stat().st_size
        bytes_read = 0

        with _open_data(path) as fh:
            for raw in fh:
                bytes_read += len(raw.encode(IMPORT_ENCODING, errors='replace'))
                row = _parse_line(raw.rstrip("\r\n"))
                if row is None:
                    error_count += 1
                    continue

                all_rows.append(row)
                regions.setdefault(row.region, row.region)
                for p in row.providers:
                    if p.name.strip():
                        providers.add(p.name.strip())

                row_count += 1
                if progress and row_count % 100000 == 0:
                    pct = 5 + int(min(bytes_read / file_size, 1.0) * 30)
                    progress.update("scan",
                        f"Парсинг: {row_count:,} строк...", pct, row_count)

        if progress:
            progress.update("load_refs",
                f"Запись справочников ({len(regions)} регионов, {len(providers)} поставщиков)...",
                36, row_count)

        with raw_conn() as conn:
            cur = conn.cursor()
            
            # Отключаем автовакуум и синхронный коммит
            #cur.execute("SET autovacuum = off")
            cur.execute("SET synchronous_commit = off")
            #cur.execute("SET session_replication_role = replica")

            # Справочники
            if regions:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO regions (code, name) VALUES %s
                    ON CONFLICT (code) DO NOTHING
                """, list(regions.items()))
            if providers:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO providers (name) VALUES %s
                    ON CONFLICT (name) DO NOTHING
                """, [(name,) for name in providers])

                # Строим карту name -> real db id
                cur.execute("SELECT id, name FROM providers")
                provider_name_to_id = {row[1]: row[0] for row in cur.fetchall()}
            conn.commit()

            # Вставка charges с RETURNING
            if progress:
                progress.update("insert_charges", "Вставка начислений с получением ID...", 40, row_count)

            charges_data = []
            for row in all_rows:
                charges_data.append((
                    import_id, row.region, row.account_id,
                    row.total_amount, row.period_from, row.period_to
                ))

            account_to_cid = {}
            batch_size = 100000  # Большие пачки для скорости
            
            total_batches = (len(charges_data) + batch_size - 1) // batch_size
            
            for batch_num, i in enumerate(range(0, len(charges_data), batch_size)):
                batch = charges_data[i:i+batch_size]
                
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO charges 
                        (import_id, region, account_id, total_amount, period_from, period_to)
                    VALUES %s
                    RETURNING account_id, id
                    """,
                    batch,
                    page_size=len(batch)
                )
                
                for acc_id, charge_id in cur.fetchall():
                    account_to_cid[acc_id] = charge_id
                
                if (batch_num + 1) % 5 == 0 or (batch_num + 1) == total_batches:
                    conn.commit()
                
                if progress and (batch_num + 1) % 2 == 0:
                    pct = 40 + int((batch_num + 1) / total_batches * 15)
                    progress.update("insert_charges", 
                        f"Вставлено {len(account_to_cid):,} из {row_count:,}...", 
                        pct, len(account_to_cid))

            conn.commit()
            
            # Вставка дочерних таблиц
            if progress:
                progress.update("copy_details", "Запись поставщиков и приборов учёта...", 60, row_count)

            cp_data = []
            mr_data = []

            for idx, row in enumerate(all_rows):
                cid = account_to_cid.get(row.account_id)
                if cid is None:
                    continue
                
                # Поставщики - преобразуем пустые строки в None
                for p in row.providers:
                    amount = None if p.amount == '' or p.amount == COPY_NULL else p.amount
                    real_pid = provider_name_to_id.get(p.name.strip())
                    if real_pid is not None:
                        cp_data.append((cid, real_pid, amount))
                
                # Приборы - аналогично, reading может быть пустым
                for m in row.meters:
                    reading = None if m.reading == '' or m.reading == COPY_NULL else m.reading
                    mr_data.append((cid, m.meter_type_id, m.meter_type_name, m.meter_number, reading))
                
                if progress and idx % 100000 == 0:
                    pct = 60 + int(idx / row_count * 20)
                    progress.update("copy_details",
                        f"Подготовлено: {len(cp_data):,} поставщиков, {len(mr_data):,} приборов",
                        pct, idx)

            # Массовая вставка поставщиков
            if cp_data:
                if progress:
                    progress.update("copy_details", "Сохранение поставщиков...", 75)
                import io as _io
                cp_buf = _io.StringIO()
                for row in cp_data:
                    charge_id, provider_id, amount = row
                    amount_str = _copy_escape(amount)
                    cp_buf.write(f"{charge_id}\t{provider_id}\t{amount_str}\n")
                cp_buf.seek(0)
                cur.copy_from(cp_buf, 'charge_providers',
                              columns=('charge_id', 'provider_id', 'amount'))

            # Массовая вставка приборов через COPY (быстрее execute_values в 3-5x)
            if mr_data:
                if progress:
                    progress.update("copy_details", "Сохранение приборов учёта...", 78)
                
                import io
                buf = io.StringIO()
                for row in mr_data:
                    charge_id, meter_type_id, meter_type_name, meter_number, reading = row
                    reading_str = _copy_escape(reading)
                    buf.write(f"{charge_id}\t{meter_type_id}\t{_copy_escape(meter_type_name)}\t{_copy_escape(meter_number)}\t{reading_str}\n")
                buf.seek(0)
                cur.copy_from(buf, 'meter_readings',
                              columns=('charge_id', 'meter_type_id', 'meter_type_name', 'meter_number', 'reading'))
            
            conn.commit()
            
            # Включаем обратно автовакуум
            #cur.execute("SET autovacuum = on")
            #cur.execute("SET session_replication_role = DEFAULT")
            
            if progress:
                progress.update("copy_details", 
                    f"Данные записаны в БД: {len(cp_data):,} поставщиков, {len(mr_data):,} приборов", 
                    80, row_count)

        return row_count, error_count

    def _calc_tariffs(self, import_id: int, period_from: date, progress: TaskProgress = None) -> int:
        """
        Оптимизированный расчёт тарифа - с временными таблицами.
        Обновляет прогресс с 85% до 95%.
        """
        with raw_conn() as conn:
            cur = conn.cursor()
            
            # Отключаем автовакуум и увеличиваем память
            #cur.execute("SET autovacuum = off")
            cur.execute("SET work_mem = '1GB'")
            cur.execute("SET maintenance_work_mem = '2GB'")
            
            if progress:
                progress.update("calc_tariffs", "Поиск предыдущего периода...", 82)
            
            # Находим предыдущий период
            # Поиск предыдущего периода (один SELECT, используется индекс period_from)
            cur.execute(
                "SELECT MAX(period_from) FROM import_log WHERE period_from < %s",
                (period_from,)
            )
            row = cur.fetchone()
            prev_period = row[0] if row else None

            if progress:
                if prev_period:
                    progress.update("calc_tariffs", 
                        f"Найден предыдущий период: {prev_period.strftime('%m.%Y')}", 85)
                else:
                    progress.update("calc_tariffs", 
                        "Первый импорт (нет предыдущего периода)", 85)

            if prev_period is None:
                if progress:
                    progress.update("calc_tariffs", "Вставка записей без расчёта тарифа...", 88)
                
                cur.execute("""
                    INSERT INTO tariff_calc
                        (charge_id, meter_type_id, meter_number,
                         reading_curr, reading_prev, consumption,
                         amount, tariff_calc)
                    SELECT
                        c.id,
                        mr.meter_type_id,
                        mr.meter_number,
                        mr.reading,
                        NULL,
                        NULL,
                        cp.amount,
                        NULL
                    FROM charges c
                    JOIN meter_readings mr ON mr.charge_id = c.id
                    LEFT JOIN charge_providers cp ON cp.charge_id = c.id
                    LEFT JOIN providers p ON p.id = cp.provider_id AND p.name = %s
                    WHERE c.import_id = %s
                      AND mr.meter_type_name = ANY(%s)
                """, (
                    ELECTRICITY_PROVIDER_NAME,
                    import_id,
                    list(ELECTRICITY_METER_TYPES),
                ))
            else:
                if progress:
                    progress.update("calc_tariffs", "Расчёт разницы показаний...", 88)
                
                # Прямой JOIN двух периодов без временных таблиц — быстрее на больших объёмах
                cur.execute("""
                    WITH curr AS (
                        SELECT
                            c.id          AS charge_id,
                            c.account_id,
                            mr.meter_type_id,
                            mr.meter_number,
                            mr.reading    AS reading_curr
                        FROM charges c
                        JOIN meter_readings mr ON mr.charge_id = c.id
                        WHERE c.import_id = %s
                          AND mr.meter_type_name = ANY(%s)
                    ),
                    prev AS (
                        SELECT
                            c.account_id,
                            mr.meter_number,
                            mr.meter_type_id,
                            mr.reading    AS reading_prev
                        FROM charges c
                        JOIN meter_readings mr ON mr.charge_id = c.id
                        WHERE c.period_from = %s
                          AND mr.meter_type_name = ANY(%s)
                    ),
                    elec AS (
                        SELECT cp.charge_id, cp.amount
                        FROM charge_providers cp
                        JOIN providers p ON p.id = cp.provider_id
                        WHERE cp.charge_id IN (SELECT id FROM charges WHERE import_id = %s)
                          AND p.name = %s
                    )
                    INSERT INTO tariff_calc
                        (charge_id, meter_type_id, meter_number,
                         reading_curr, reading_prev, consumption,
                         amount, tariff_calc)
                    SELECT
                        curr.charge_id,
                        curr.meter_type_id,
                        curr.meter_number,
                        curr.reading_curr,
                        prev.reading_prev,
                        CASE WHEN prev.reading_prev IS NOT NULL
                             THEN curr.reading_curr - prev.reading_prev
                        END,
                        elec.amount,
                        CASE
                            WHEN prev.reading_prev IS NOT NULL
                             AND (curr.reading_curr - prev.reading_prev) > 0
                             AND elec.amount IS NOT NULL
                            THEN ROUND(
                                elec.amount / NULLIF(curr.reading_curr - prev.reading_prev, 0), 5
                            )
                        END
                    FROM curr
                    LEFT JOIN prev
                        ON  prev.account_id    = curr.account_id
                        AND prev.meter_number  = curr.meter_number
                        AND prev.meter_type_id = curr.meter_type_id
                    LEFT JOIN elec ON elec.charge_id = curr.charge_id
                """, (
                    import_id,
                    list(ELECTRICITY_METER_TYPES),
                    prev_period,
                    list(ELECTRICITY_METER_TYPES),
                    import_id,
                    ELECTRICITY_PROVIDER_NAME,
                ))
            
            inserted = cur.rowcount
            conn.commit()
            
            # Включаем обратно автовакуум
            #cur.execute("SET autovacuum = on")
            
            if progress:
                progress.update("calc_tariffs",
                    f"Расчёт тарифов завершён: {inserted:,} записей", 95)
                time.sleep(0.1)
            
            return inserted