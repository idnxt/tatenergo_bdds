-- 001_init.sql
-- Полная инициализация схемы tatenergo_bdds
-- Запускается один раз при первом старте (через init_db.py)
-- Включает все изменения из 002_optimize_storage.sql и 006_tariff_precision.sql

-- ─── Справочник регионов ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regions (
    code VARCHAR(12) PRIMARY KEY,
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
    import_id    INTEGER      NOT NULL REFERENCES import_log(id),
    region       VARCHAR(12)  NOT NULL REFERENCES regions(code),
    account_id   VARCHAR(10)  NOT NULL,
    total_amount NUMERIC(12,2),
    period_from  DATE         NOT NULL,
    period_to    DATE         NOT NULL
) WITH (fillfactor = 100);

CREATE INDEX IF NOT EXISTS idx_charges_region       ON charges(region);
CREATE INDEX IF NOT EXISTS idx_charges_import       ON charges(import_id);

-- ─── Справочник поставщиков ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS providers (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    CONSTRAINT providers_name_unique UNIQUE (name)
);

-- ─── Начисления по поставщикам ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS charge_providers (
    id          BIGSERIAL PRIMARY KEY,
    charge_id   BIGINT  NOT NULL REFERENCES charges(id),
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    amount      NUMERIC(12,2)
) WITH (fillfactor = 100);

CREATE INDEX IF NOT EXISTS idx_cp_provider    ON charge_providers(provider_id);

-- ─── Показания приборов учёта ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meter_readings (
    id              BIGSERIAL PRIMARY KEY,
    charge_id       BIGINT      NOT NULL REFERENCES charges(id),
    meter_type_id   INTEGER     NOT NULL,
    meter_type_name VARCHAR(60) NOT NULL,
    meter_number    VARCHAR(50) NOT NULL,
    reading         NUMERIC(15,3)
) WITH (fillfactor = 100);

CREATE INDEX IF NOT EXISTS idx_mr_type      ON meter_readings(meter_type_id);
CREATE INDEX IF NOT EXISTS idx_mr_num_type  ON meter_readings(meter_number, meter_type_id);

-- ─── Расчётные тарифы и аномалии ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tariff_calc (
    id             BIGSERIAL PRIMARY KEY,
    charge_id      BIGINT      NOT NULL REFERENCES charges(id),
    meter_type_id  INTEGER     NOT NULL,
    meter_number   VARCHAR(50) NOT NULL,
    reading_curr   NUMERIC(15,3),
    reading_prev   NUMERIC(15,3),
    consumption    NUMERIC(15,3),
    amount         NUMERIC(12,2),
    tariff_calc    NUMERIC(12,5),
    is_anomaly     BOOLEAN     NOT NULL DEFAULT false,
    anomaly_reason TEXT
) WITH (fillfactor = 100);

CREATE INDEX IF NOT EXISTS idx_tc_anomaly ON tariff_calc(is_anomaly) WHERE is_anomaly = true;
CREATE INDEX IF NOT EXISTS idx_tc_type    ON tariff_calc(meter_type_id);

-- Индексы не создаются при инициализации.
-- Запусти rebuild_indexes.py после загрузки всех файлов.
