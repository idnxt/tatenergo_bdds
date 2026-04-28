-- 006_tariff_precision.sql
-- NUMERIC(8,5) переполнялся при аномальных тарифах (> 999 руб/кВт).
-- Расширяем до NUMERIC(12,5) — допускает до 9 999 999.99999.
ALTER TABLE tariff_calc
    ALTER COLUMN tariff_calc TYPE NUMERIC(12,5);
