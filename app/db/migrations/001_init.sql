-- 001_init.sql
-- Полная инициализация схемы tatenergo_bdds
-- Запускается один раз при первом старте (через init_db.py)

-- ─── Справочник регионов ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regions (
    code VARCHAR(30) PRIMARY KEY,
    name VARCHAR(255) NOT NULL
);

-- ─── Журнал импортов ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS import_log (
    id           SERIAL PRIMARY KEY,
    period_from  DATE        NOT NULL,
    period_to    DATE        NOT NULL,
    filename     VARCHAR(255),
    filesum      NUMERIC(18,2),
    loaded_at    TIMESTAMP   NOT NULL DEFAULT now(),
    row_count    INTEGER,
    error_count  INTEGER     DEFAULT 0,
    duration_sec INTEGER,
    CONSTRAINT uq_import_period UNIQUE (period_from)
);

-- ─── Начисления (основная таблица) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS charges (
    id           BIGSERIAL PRIMARY KEY,
    import_id    INTEGER     NOT NULL REFERENCES import_log(id),
    region       VARCHAR(30) NOT NULL REFERENCES regions(code),
    account_id   VARCHAR(30) NOT NULL,
    total_amount NUMERIC(14,2),
    period_from  DATE        NOT NULL,
    period_to    DATE        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_charges_account  ON charges(account_id);
CREATE INDEX IF NOT EXISTS idx_charges_region   ON charges(region);
CREATE INDEX IF NOT EXISTS idx_charges_period   ON charges(period_from);
CREATE INDEX IF NOT EXISTS idx_charges_import   ON charges(import_id);
-- Составной: самый частый запрос в отчётах
CREATE INDEX IF NOT EXISTS idx_charges_region_period ON charges(region, period_from);

-- ─── Справочник поставщиков ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS providers (
    id   INTEGER PRIMARY KEY,   -- id из файла (13, 24, 63 ...)
    name VARCHAR(255) NOT NULL
);

-- ─── Начисления по поставщикам ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS charge_providers (
    id          BIGSERIAL PRIMARY KEY,
    charge_id   BIGINT  NOT NULL REFERENCES charges(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    amount      NUMERIC(14,2)
);

CREATE INDEX IF NOT EXISTS idx_cp_charge    ON charge_providers(charge_id);
CREATE INDEX IF NOT EXISTS idx_cp_provider  ON charge_providers(provider_id);
-- Для агрегации по поставщику за период (через JOIN с charges)
CREATE INDEX IF NOT EXISTS idx_cp_prov_amount ON charge_providers(provider_id, amount);

-- ─── Показания приборов учёта ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meter_readings (
    id              BIGSERIAL PRIMARY KEY,
    charge_id       BIGINT       NOT NULL REFERENCES charges(id),
    meter_type_id   INTEGER      NOT NULL,
    meter_type_name VARCHAR(100) NOT NULL,
    meter_number    VARCHAR(50)  NOT NULL,
    reading         NUMERIC(14,3)
);

CREATE INDEX IF NOT EXISTS idx_mr_charge     ON meter_readings(charge_id);
CREATE INDEX IF NOT EXISTS idx_mr_type       ON meter_readings(meter_type_id);
CREATE INDEX IF NOT EXISTS idx_mr_meter_num  ON meter_readings(meter_number);
-- Для поиска предыдущих показаний: account + номер прибора
-- (через JOIN meter_readings → charges)
CREATE INDEX IF NOT EXISTS idx_mr_num_type   ON meter_readings(meter_number, meter_type_id);

-- ─── Расчётные тарифы и аномалии ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tariff_calc (
    id             BIGSERIAL PRIMARY KEY,
    charge_id      BIGINT      NOT NULL REFERENCES charges(id),
    meter_type_id  INTEGER     NOT NULL,
    meter_number   VARCHAR(50) NOT NULL,
    reading_curr   NUMERIC(14,3),
    reading_prev   NUMERIC(14,3),
    consumption    NUMERIC(14,3),
    amount         NUMERIC(14,2),
    tariff_calc    NUMERIC(10,5),
    is_anomaly     BOOLEAN     NOT NULL DEFAULT false,
    anomaly_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_tc_charge   ON tariff_calc(charge_id);
CREATE INDEX IF NOT EXISTS idx_tc_anomaly  ON tariff_calc(is_anomaly) WHERE is_anomaly = true;
CREATE INDEX IF NOT EXISTS idx_tc_meter    ON tariff_calc(meter_number);
CREATE INDEX IF NOT EXISTS idx_tc_type     ON tariff_calc(meter_type_id);
