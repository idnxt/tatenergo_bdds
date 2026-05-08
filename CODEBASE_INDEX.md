# tatenergo_bdds Codebase Index

## Overview

This repository is a portable FastAPI-based analytics application for ЖКУ billing data from ТАТЭНЕРГОСБЫТ.

- `start.bat` / `stop.bat`: local app lifecycle helpers.
- `init_db.py`: database initialization script.
- `requirements.txt`: Python dependencies.
- `pgsql/`: portable PostgreSQL binaries.
- `pgdata/`: PostgreSQL data directory.
- `data/`: input file staging directory.
- `tmp/`: temporary utilities and cleanup scripts.

## app/

### app/main.py

- Creates the FastAPI application.
- Registers router modules:
  - `/import` → importer UI and upload flow.
  - `/reports` → summary reports.
  - `/reports/provider` → provider billing reports.
  - `/reports/account-detail` → account-level detail reports.
- Uses Jinja2 templates from `app/templates/`.
- On startup, checks PostgreSQL connection and removes incomplete import records.

### app/config.py

Central configuration values:
- PostgreSQL paths, connection strings, port settings.
- Application host and port.
- Import settings: batch size, encoding.
- Provider constants for tariff calculation.
- Ensures `data/` directory exists.

## app/db/

### app/db/engine.py

- `engine`: SQLAlchemy engine for ORM and migrations.
- `SessionLocal`: SQLAlchemy session factory.
- `Base`: declarative base for ORM models.
- `get_db()`: FastAPI dependency for request-scoped DB sessions.
- `raw_conn()`: psycopg2 connection context manager for bulk COPY operations.
- `check_connection()`: startup DB health check.

### app/db/models.py

ORM models matching the DB schema:
- `Region`
- `ImportLog`
- `Charge`
- `Provider`
- `ChargeProvider`
- `MeterReading`
- `TariffCalc`

Relationships are configured for import history, charges, providers, meter readings, and tariff calculations.

## app/modules/importer/

### app/modules/importer/router.py

- Import page GET `/import/`.
- Upload endpoint POST `/import/upload`.
- SSE endpoint `/import/progress/queue` for real-time progress updates.
- Uses `TaskProgress` and `ImportQueue`.

### app/modules/importer/service.py

Import pipeline for file processing:
- Header parsing and period detection.
- Duplicate period check.
- Bulk insert via PostgreSQL COPY/INSERT.
- Import stages:
  1. Parse and scan file.
  2. Insert/upsert `regions` and `providers`.
  3. Insert `charges` with `RETURNING id`.
  4. Insert `charge_providers` and `meter_readings`.
  5. Tariff calculation into `tariff_calc`.
- Includes rollback on failure and progress updates.
- Supports CP1251/ANSI file encoding.

### app/modules/importer/progress.py

- `TaskProgress`: per-file progress state.
- `ImportQueue`: thread-backed queue for serialized import execution.
- SSE-based progress updates are broadcast to the browser.

## app/modules/reports/

### app/modules/reports/router.py

- Report landing page at `/reports/`.
- Summary report page at `/reports/summary/{import_id}`.
- Uses `ReportService`.

### app/modules/reports/service.py

Summary report service:
- Period list from `import_log`.
- Total charge amount, region breakdown, top providers.
- Meter type counts and anomaly listing.
- Chart data preparation.

### app/modules/reports/provider_router.py

Provider billing report routes:
- `/reports/provider` page.
- JSON endpoints for periods, providers, and calculate report.
- Handles provider selection and period range.

### app/modules/reports/provider_report.py

Provider report service:
- Loads periods and providers.
- Calculates monthly sums for selected providers.
- Builds stats table with MoM and YoY changes.
- Computes top-20 accounts by provider.

### app/modules/reports/account_detail_router.py

Account detail report routes:
- `/reports/account-detail` page.
- `/reports/account-detail/calculate.json` endpoint.
- Validates account IDs and returns JSON report.

### app/modules/reports/account_detail_report.py

Account detail service:
- Returns per-account billing by period and provider.
- Fetches meter readings and electricity tariff calculations.
- Builds a unified history view for selected accounts.

## Templates

- `app/templates/index.html`: main dashboard.
- `app/templates/import.html`: import upload page.
- `app/templates/import_progress.html`: queue progress page.
- `app/templates/reports/`: report pages and summaries.

## Utilities

### tmp/

- `cleanup_db.py` / `cleanup_db.bat`: database cleanup utilities.
- `tune_pg.bat`: PostgreSQL tuning helper.

## Notes

- Database schema is created via migrations under `app/db/migrations/`.
- The app depends on portable PostgreSQL in `pgsql/` and data directory `pgdata/`.
- The user-visible flow is primarily import → reports.
- Bulk import is optimized for large text files and uses direct psycopg2 COPY+INSERT.
