"""
calc_tariffs_batch.py — расчёт тарифов для всех периодов одновременно.

Используется после загрузки всех файлов. Намного быстрее чем считать
после каждого импорта, потому что JOIN оптимизируется на весь датасет.

Использование:
  python -m app.modules.importer.calc_tariffs_batch [--period-from YYYY-MM-DD]
"""
import sys
from datetime import date
from app.db.engine import raw_conn
from app.config import ELECTRICITY_PROVIDER_NAME, ELECTRICITY_METER_TYPES


def calc_all_tariffs(period_from: date = None):
    """
    Расчёт tariff_calc для всех периодов.
    
    Если period_from задан, считаются только записи с этого периода и позже.
    Иначе пересчитываются все.
    """
    with raw_conn() as conn:
        cur = conn.cursor()
        
        # Очищаем старые тарифы если нужно пересчитать
        if period_from:
            print(f"[TARIFF] Очистка тарифов с {period_from.strftime('%m.%Y')}...")
            cur.execute(
                "DELETE FROM tariff_calc "
                "WHERE charge_id IN (SELECT id FROM charges WHERE period_from >= %s)",
                (period_from,)
            )
        else:
            print("[TARIFF] Очистка всех тарифов...")
            cur.execute("DELETE FROM tariff_calc")
        
        conn.commit()
        print(f"[TARIFF] Удалено записей из tariff_calc")
        
        # Основной расчёт
        print("[TARIFF] Расчёт тарифов...")
        cur.execute("""
            WITH curr AS (
                SELECT
                    c.id          AS charge_id,
                    c.account_id,
                    mr.meter_type_id,
                    mr.meter_number,
                    mr.reading    AS reading_curr,
                    c.period_from
                FROM charges c
                JOIN meter_readings mr ON mr.charge_id = c.id
                WHERE mr.meter_type_name = ANY(%s)
            ),
            prev AS (
                SELECT
                    c.account_id,
                    mr.meter_number,
                    mr.meter_type_id,
                    mr.reading    AS reading_prev,
                    c.period_from
                FROM charges c
                JOIN meter_readings mr ON mr.charge_id = c.id
                WHERE mr.meter_type_name = ANY(%s)
            ),
            curr_with_prev AS (
                SELECT
                    curr.charge_id,
                    curr.meter_type_id,
                    curr.meter_number,
                    curr.reading_curr,
                    prev.reading_prev,
                    curr.period_from
                FROM curr
                LEFT JOIN prev
                    ON  prev.account_id    = curr.account_id
                    AND prev.meter_number  = curr.meter_number
                    AND prev.meter_type_id = curr.meter_type_id
                    AND prev.period_from = (
                        SELECT MAX(c2.period_from)
                        FROM charges c2
                        WHERE c2.period_from < curr.period_from
                          AND c2.account_id = curr.account_id
                    )
            ),
            elec AS (
                SELECT cp.charge_id, cp.amount
                FROM charge_providers cp
                JOIN providers p ON p.id = cp.provider_id
                WHERE p.name = %s
            )
            INSERT INTO tariff_calc
                (charge_id, meter_type_id, meter_number,
                 reading_curr, reading_prev, consumption,
                 amount, tariff_calc)
            SELECT
                cwp.charge_id,
                cwp.meter_type_id,
                cwp.meter_number,
                cwp.reading_curr,
                cwp.reading_prev,
                CASE WHEN cwp.reading_prev IS NOT NULL
                     THEN cwp.reading_curr - cwp.reading_prev
                END,
                elec.amount,
                CASE
                    WHEN cwp.reading_prev IS NOT NULL
                     AND (cwp.reading_curr - cwp.reading_prev) > 0
                     AND elec.amount IS NOT NULL
                    THEN ROUND(
                        elec.amount / NULLIF(cwp.reading_curr - cwp.reading_prev, 0), 5
                    )
                END
            FROM curr_with_prev cwp
            LEFT JOIN elec ON elec.charge_id = cwp.charge_id
        """, (
            list(ELECTRICITY_METER_TYPES),
            list(ELECTRICITY_METER_TYPES),
            ELECTRICITY_PROVIDER_NAME,
        ))
        
        inserted = cur.rowcount
        conn.commit()
        print(f"[TARIFF] Вставлено {inserted:,} записей в tariff_calc")
        return inserted


if __name__ == "__main__":
    period_from = None
    if len(sys.argv) > 2 and sys.argv[1] == "--period-from":
        try:
            period_from = date.fromisoformat(sys.argv[2])
        except ValueError:
            print(f"Ошибка: неверный формат даты {sys.argv[2]}, используйте YYYY-MM-DD")
            sys.exit(1)
    
    try:
        calc_all_tariffs(period_from)
        print("[TARIFF] Готово")
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
