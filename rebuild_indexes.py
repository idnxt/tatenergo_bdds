"""
rebuild_indexes.py
Создаёт все индексы после загрузки всех файлов.
Запускать: python rebuild_indexes.py
"""
import time
import sys
from app.db.engine import raw_conn

INDEXES = [
    # charges
    ("idx_charges_account",       "CREATE INDEX IF NOT EXISTS idx_charges_account       ON charges(account_id)"),
    ("idx_charges_region",        "CREATE INDEX IF NOT EXISTS idx_charges_region        ON charges(region)"),
    ("idx_charges_period",        "CREATE INDEX IF NOT EXISTS idx_charges_period        ON charges(period_from)"),
    ("idx_charges_import",        "CREATE INDEX IF NOT EXISTS idx_charges_import        ON charges(import_id)"),
    ("idx_charges_region_period", "CREATE INDEX IF NOT EXISTS idx_charges_region_period ON charges(region, period_from)"),

    # charge_providers
    ("idx_cp_charge",             "CREATE INDEX IF NOT EXISTS idx_cp_charge             ON charge_providers(charge_id)"),
    ("idx_cp_provider",           "CREATE INDEX IF NOT EXISTS idx_cp_provider           ON charge_providers(provider_id)"),
    ("idx_cp_prov_amount",        "CREATE INDEX IF NOT EXISTS idx_cp_prov_amount        ON charge_providers(provider_id, amount)"),

    # meter_readings
    ("idx_mr_charge",             "CREATE INDEX IF NOT EXISTS idx_mr_charge             ON meter_readings(charge_id)"),
    ("idx_mr_type",               "CREATE INDEX IF NOT EXISTS idx_mr_type               ON meter_readings(meter_type_id)"),
    ("idx_mr_meter_num",          "CREATE INDEX IF NOT EXISTS idx_mr_meter_num          ON meter_readings(meter_number)"),
    ("idx_mr_num_type",           "CREATE INDEX IF NOT EXISTS idx_mr_num_type           ON meter_readings(meter_number, meter_type_id)"),

    # tariff_calc
    ("idx_tc_charge",             "CREATE INDEX IF NOT EXISTS idx_tc_charge             ON tariff_calc(charge_id)"),
    ("idx_tc_anomaly",            "CREATE INDEX IF NOT EXISTS idx_tc_anomaly            ON tariff_calc(is_anomaly) WHERE is_anomaly = true"),
    ("idx_tc_meter",              "CREATE INDEX IF NOT EXISTS idx_tc_meter              ON tariff_calc(meter_number)"),
    ("idx_tc_type",               "CREATE INDEX IF NOT EXISTS idx_tc_type               ON tariff_calc(meter_type_id)"),
]

def main():
    print(f"Создание {len(INDEXES)} индексов...")
    total_t0 = time.time()

    with raw_conn() as conn:
        conn.autocommit = True
        cur = conn.cursor()

        for i, (name, sql) in enumerate(INDEXES, 1):
            t0 = time.time()
            print(f"[{i}/{len(INDEXES)}] {name}...", end=" ", flush=True)
            cur.execute(sql)
            elapsed = time.time() - t0
            print(f"{elapsed:.1f} сек")

    total = time.time() - total_t0
    print(f"\n✓ Готово! Все индексы созданы за {total:.0f} сек ({total/60:.1f} мин)")

if __name__ == "__main__":
    main()
