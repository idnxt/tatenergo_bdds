-- 002_optimize_storage.sql
-- Оптимизация типов данных.
-- Размеры полей выверены по реальным данным (см. миграции 003-005).

-- charges: account_id и region по реальной длине данных
ALTER TABLE charges
    ALTER COLUMN total_amount TYPE NUMERIC(12,2),
    ALTER COLUMN account_id   TYPE VARCHAR(10),
    ALTER COLUMN region       TYPE VARCHAR(12);

-- charge_providers
ALTER TABLE charge_providers
    ALTER COLUMN amount TYPE NUMERIC(12,2);

-- meter_readings: reading 15,3 по реальным значениям счётчиков
ALTER TABLE meter_readings
    ALTER COLUMN reading         TYPE NUMERIC(15,3),
    ALTER COLUMN meter_type_name TYPE VARCHAR(60),
    ALTER COLUMN meter_number    TYPE VARCHAR(50);

-- tariff_calc: reading и consumption 15,3 для совместимости
ALTER TABLE tariff_calc
    ALTER COLUMN reading_curr TYPE NUMERIC(15,3),
    ALTER COLUMN reading_prev TYPE NUMERIC(15,3),
    ALTER COLUMN consumption  TYPE NUMERIC(15,3),
    ALTER COLUMN amount       TYPE NUMERIC(12,2),
    ALTER COLUMN tariff_calc  TYPE NUMERIC(8,5),
    ALTER COLUMN meter_number TYPE VARCHAR(50);

-- FILLFACTOR=100: таблицы только для вставки, UPDATE не делается
ALTER TABLE charges          SET (fillfactor = 100);
ALTER TABLE charge_providers SET (fillfactor = 100);
ALTER TABLE meter_readings   SET (fillfactor = 100);
ALTER TABLE tariff_calc      SET (fillfactor = 100);
