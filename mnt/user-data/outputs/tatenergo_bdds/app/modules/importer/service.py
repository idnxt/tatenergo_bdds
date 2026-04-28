"""
importer/service.py — вся логика импорта файла.

Порядок работы:
  1. Валидация заголовка (#FILESUM, #TYPE)
  2. Проверка дубля периода
  3. Потоковый парсинг строк → батчи
  4. Bulk-вставка через psycopg2 execute_values
  5. Расчёт tariff_calc для электроснабжения
  6. Фиксация в import_log
"""
import io
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import (
    IMPORT_BATCH_SIZE, IMPORT_ENCODING,
    ELECTRICITY_PROVIDER_NAME, ELECTRICITY_METER_TYPES,
)
from app.db.engine import raw_conn
from app.db import models


# ─── Структуры данных ────────────────────────────────────────────────────────

@dataclass
class ParsedProvider:
    provider_id: int
    name: str
    amount: Optional[Decimal]


@dataclass
class ParsedMeter:
    meter_type_id: int
    meter_type_name: str
    meter_number: str
    reading: Optional[Decimal]


@dataclass
class ParsedRow:
    region: str
    account_id: str
    total_amount: Optional[Decimal]
    period_from: date
    period_to: date
    providers: list[ParsedProvider] = field(default_factory=list)
    meters: list[ParsedMeter] = field(default_factory=list)


@dataclass
class ImportResult:
    success: bool
    filename: str
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    row_count: int = 0
    error_count: int = 0
    duration_sec: int = 0
    filesum: Optional[Decimal] = None
    error_message: str = ""
    tariff_rows: int = 0


# ─── Парсеры ────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> Optional[date]:
    """DD.MM.YYYY → date"""
    try:
        d, m, y = s.strip().split(".")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _parse_decimal(s: str) -> Optional[Decimal]:
    try:
        return Decimal(s.strip().replace(",", ".")) if s.strip() else None
    except InvalidOperation:
        return None


def _parse_oplata(raw: str) -> list[ParsedProvider]:
    """
    'Oplata:13:МУП "Новошешминское ЖКХ":4713.77:24:АО "ТАТЭНЕРГОСБЫТ":0.00:...'
    Группы по 3 токена: id, name, amount. Пустые тройки — пропускаем.
    """
    if not raw or not raw.startswith("Oplata:"):
        return []
    parts = raw[len("Oplata:"):].split(":")
    result = []
    i = 0
    while i + 2 < len(parts):
        pid_s, name, amount_s = parts[i], parts[i+1], parts[i+2]
        i += 3
        if not pid_s.strip():
            continue
        try:
            pid = int(pid_s.strip())
        except ValueError:
            continue
        result.append(ParsedProvider(
            provider_id=pid,
            name=name.strip(),
            amount=_parse_decimal(amount_s),
        ))
    return result


def _parse_pu(raw: str) -> list[ParsedMeter]:
    """
    'Pu:1:Холодное водоснабжение:10106314:586.000:2:Электроснабжение:051338:18153.760:...'
    Группы по 4 токена: type_id, type_name, meter_number, reading.
    """
    if not raw or not raw.startswith("Pu:"):
        return []
    parts = raw[len("Pu:"):].split(":")
    result = []
    i = 0
    while i + 3 < len(parts):
        tid_s, tname, mnum, reading_s = parts[i], parts[i+1], parts[i+2], parts[i+3]
        i += 4
        if not tid_s.strip():
            continue
        try:
            tid = int(tid_s.strip())
        except ValueError:
            continue
        result.append(ParsedMeter(
            meter_type_id=tid,
            meter_type_name=tname.strip(),
            meter_number=mnum.strip(),
            reading=_parse_decimal(reading_s),
        ))
    return result


def _parse_line(line: str) -> Optional[ParsedRow]:
    """
    Парсит одну строку данных. Возвращает None при критической ошибке.
    Поля: region;;account_id;total_amount;date_from;date_to;Oplata:...;Pu:...
    """
    parts = line.rstrip("\n\r").split(";")
    if len(parts) < 7:
        return None

    region     = parts[0].strip()
    # parts[1] — пустое поле (;;)
    account_id = parts[3].strip()
    if not region or not account_id:
        return None

    total_amount = _parse_decimal(parts[4])
    period_from  = _parse_date(parts[5])
    period_to    = _parse_date(parts[6])
    if not period_from or not period_to:
        return None

    # Ищем блоки Oplata и Pu среди оставшихся полей
    oplata_raw = next((p for p in parts[7:] if p.startswith("Oplata:")), "")
    pu_raw     = next((p for p in parts[7:] if p.startswith("Pu:")),     "")

    return ParsedRow(
        region=region,
        account_id=account_id,
        total_amount=total_amount,
        period_from=period_from,
        period_to=period_to,
        providers=_parse_oplata(oplata_raw),
        meters=_parse_pu(pu_raw),
    )


# ─── Сервис ──────────────────────────────────────────────────────────────────

class ImportService:

    def __init__(self, db: Session):
        self.db = db

    def get_history(self) -> list[models.ImportLog]:
        return (
            self.db.query(models.ImportLog)
            .order_by(models.ImportLog.period_from.desc())
            .all()
        )

    async def import_file(self, file: UploadFile) -> ImportResult:
        result = ImportResult(success=False, filename=file.filename or "unknown")
        t0 = time.time()

        # Читаем файл в память (файлы ~50-150 МБ — допустимо)
        raw_bytes = await file.read()
        try:
            text = raw_bytes.decode(IMPORT_ENCODING)
        except UnicodeDecodeError:
            result.error_message = "Ошибка декодирования файла. Ожидается ANSI (cp1251)."
            return result

        lines = text.splitlines()
        if len(lines) < 3:
            result.error_message = "Файл слишком короткий (нет заголовка или данных)."
            return result

        # Заголовок
        filesum = None
        if lines[0].startswith("#FILESUM"):
            filesum = _parse_decimal(lines[0].split()[-1])
        if not lines[1].startswith("#TYPE"):
            result.error_message = "Неверный формат заголовка (#TYPE не найден)."
            return result

        data_lines = lines[2:]

        # Определяем период из первой валидной строки
        period_from, period_to = None, None
        for l in data_lines[:100]:
            row = _parse_line(l)
            if row:
                period_from, period_to = row.period_from, row.period_to
                break

        if not period_from:
            result.error_message = "Не удалось определить расчётный период из данных файла."
            return result

        # Проверка дубля
        existing = (
            self.db.query(models.ImportLog)
            .filter(models.ImportLog.period_from == period_from)
            .first()
        )
        if existing:
            result.error_message = (
                f"Период {period_from.strftime('%m.%Y')} уже загружен "
                f"(импорт #{existing.id} от {existing.loaded_at.strftime('%d.%m.%Y %H:%M')})."
            )
            return result

        result.period_from = period_from
        result.period_to   = period_to
        result.filesum     = filesum

        # Создаём запись import_log (без row_count — заполним в конце)
        import_log = models.ImportLog(
            period_from=period_from,
            period_to=period_to,
            filename=file.filename,
            filesum=filesum,
        )
        self.db.add(import_log)
        self.db.flush()  # получаем import_log.id
        import_id = import_log.id

        # Bulk-вставка
        row_count, error_count = self._bulk_insert(data_lines, import_id)

        # Расчёт тарифов
        tariff_rows = self._calc_tariffs(import_id, period_from)

        # Финализация import_log
        import_log.row_count    = row_count
        import_log.error_count  = error_count
        import_log.duration_sec = int(time.time() - t0)
        self.db.commit()

        result.success     = True
        result.row_count   = row_count
        result.error_count = error_count
        result.duration_sec = import_log.duration_sec
        result.tariff_rows = tariff_rows
        return result

    def _bulk_insert(self, lines: list[str], import_id: int) -> tuple[int, int]:
        """
        Парсим строки батчами, вставляем через psycopg2 execute_values.
        Возвращает (кол-во успешных, кол-во ошибок).
        """
        import psycopg2.extras

        row_count   = 0
        error_count = 0
        batch_rows: list[ParsedRow] = []

        with raw_conn() as conn:
            cur = conn.cursor()

            def flush_batch(batch: list[ParsedRow]):
                nonlocal row_count
                if not batch:
                    return

                # 1. Upsert регионов
                regions = {r.region for r in batch}
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO regions (code, name)
                    VALUES %s
                    ON CONFLICT (code) DO NOTHING
                """, [(c, c) for c in regions])

                # 2. Upsert поставщиков
                providers: dict[int, str] = {}
                for r in batch:
                    for p in r.providers:
                        providers[p.provider_id] = p.name
                if providers:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO providers (id, name)
                        VALUES %s
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                    """, list(providers.items()))

                # 3. Вставка charges
                charge_data = [
                    (import_id, r.region, r.account_id,
                     r.total_amount, r.period_from, r.period_to)
                    for r in batch
                ]
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO charges
                        (import_id, region, account_id, total_amount, period_from, period_to)
                    VALUES %s
                    RETURNING id
                """, charge_data, fetch=True)
                charge_ids = [row[0] for row in cur.fetchall()]

                # 4. Начисления по поставщикам
                cp_data = []
                for charge_id, row in zip(charge_ids, batch):
                    for p in row.providers:
                        cp_data.append((charge_id, p.provider_id, p.amount))
                if cp_data:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO charge_providers (charge_id, provider_id, amount)
                        VALUES %s
                    """, cp_data)

                # 5. Показания приборов
                mr_data = []
                for charge_id, row in zip(charge_ids, batch):
                    for m in row.meters:
                        mr_data.append((
                            charge_id, m.meter_type_id, m.meter_type_name,
                            m.meter_number, m.reading,
                        ))
                if mr_data:
                    psycopg2.extras.execute_values(cur, """
                        INSERT INTO meter_readings
                            (charge_id, meter_type_id, meter_type_name, meter_number, reading)
                        VALUES %s
                    """, mr_data)

                conn.commit()
                row_count += len(batch)

            # Основной цикл
            for line in lines:
                if not line.strip():
                    continue
                try:
                    parsed = _parse_line(line)
                    if parsed is None:
                        error_count += 1
                        continue
                    batch_rows.append(parsed)
                    if len(batch_rows) >= IMPORT_BATCH_SIZE:
                        flush_batch(batch_rows)
                        batch_rows = []
                except Exception:
                    error_count += 1

            flush_batch(batch_rows)  # остаток

        return row_count, error_count

    def _calc_tariffs(self, import_id: int, period_from: date) -> int:
        """
        После вставки всех данных:
        - Находит предыдущий месяц
        - Джойнит текущие и предыдущие показания электросчётчиков
        - Вычисляет расход и тариф
        - Вставляет в tariff_calc

        Возвращает кол-во вставленных строк.
        """
        with raw_conn() as conn:
            cur = conn.cursor()

            # Имена типов электросчётчиков (из config)
            meter_types_tuple = tuple(ELECTRICITY_METER_TYPES)

            # SQL: соединяем текущие показания с предыдущими и суммой от ТАТЭНЕРГОСБЫТ
            cur.execute("""
                WITH curr_month AS (
                    -- текущие показания электросчётчиков
                    SELECT
                        c.id          AS charge_id,
                        c.account_id,
                        mr.meter_type_id,
                        mr.meter_type_name,
                        mr.meter_number,
                        mr.reading    AS reading_curr
                    FROM charges c
                    JOIN meter_readings mr ON mr.charge_id = c.id
                    WHERE c.import_id = %s
                      AND mr.meter_type_name = ANY(%s)
                ),
                prev_month AS (
                    -- показания предыдущего периода
                    SELECT
                        c.account_id,
                        mr.meter_number,
                        mr.meter_type_id,
                        mr.reading    AS reading_prev
                    FROM charges c
                    JOIN import_log il ON il.id = c.import_id
                    JOIN meter_readings mr ON mr.charge_id = c.id
                    WHERE il.period_from = (
                              SELECT MAX(il2.period_from)
                              FROM import_log il2
                              WHERE il2.period_from < %s
                          )
                      AND mr.meter_type_name = ANY(%s)
                ),
                elec_amounts AS (
                    -- сумма от ТАТЭНЕРГОСБЫТ для каждого лицевого счёта
                    SELECT
                        c.id  AS charge_id,
                        cp.amount
                    FROM charges c
                    JOIN charge_providers cp ON cp.charge_id = c.id
                    JOIN providers p         ON p.id = cp.provider_id
                    WHERE c.import_id = %s
                      AND p.name = %s
                )
                INSERT INTO tariff_calc
                    (charge_id, meter_type_id, meter_number,
                     reading_curr, reading_prev, consumption,
                     amount, tariff_calc)
                SELECT
                    cm.charge_id,
                    cm.meter_type_id,
                    cm.meter_number,
                    cm.reading_curr,
                    pm.reading_prev,
                    CASE
                        WHEN pm.reading_prev IS NOT NULL
                        THEN cm.reading_curr - pm.reading_prev
                        ELSE NULL
                    END AS consumption,
                    ea.amount,
                    CASE
                        WHEN pm.reading_prev IS NOT NULL
                          AND (cm.reading_curr - pm.reading_prev) > 0
                          AND ea.amount IS NOT NULL
                        THEN ROUND(ea.amount / (cm.reading_curr - pm.reading_prev), 5)
                        ELSE NULL
                    END AS tariff_calc
                FROM curr_month cm
                LEFT JOIN prev_month pm
                    ON  pm.account_id    = cm.account_id
                    AND pm.meter_number  = cm.meter_number
                    AND pm.meter_type_id = cm.meter_type_id
                LEFT JOIN elec_amounts ea ON ea.charge_id = cm.charge_id
            """, (
                import_id,
                list(ELECTRICITY_METER_TYPES),
                period_from,
                list(ELECTRICITY_METER_TYPES),
                import_id,
                ELECTRICITY_PROVIDER_NAME,
            ))

            inserted = cur.rowcount
            conn.commit()
            return inserted
