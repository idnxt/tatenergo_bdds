"""
tatenergo_bdds — центральная конфигурация
Все пути и параметры берутся отсюда. Для смены окружения — только этот файл.
"""
import os
from pathlib import Path

# Корень проекта (папка, где лежит start.bat)
BASE_DIR = Path(__file__).resolve().parent.parent

# --- PostgreSQL portable ---
PG_DIR        = BASE_DIR / "pgsql"
PG_BIN        = PG_DIR / "bin"
PG_DATA       = BASE_DIR / "pgdata"
PG_LOG        = BASE_DIR / "pgdata" / "pg.log"
PG_PORT       = int(os.getenv("PG_PORT", "5433"))   # 5433 чтобы не конфликтовать с системным PG
PG_DB         = os.getenv("PG_DB",   "tatenergo")
PG_USER       = os.getenv("PG_USER", "tatenergo")
PG_PASSWORD   = os.getenv("PG_PASS", "tatenergo")

DATABASE_URL = (
    f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}"
    f"@localhost:{PG_PORT}/{PG_DB}"
)

# DSN для psycopg2 напрямую (bulk COPY)
PG_DSN = (
    f"host=localhost port={PG_PORT} dbname={PG_DB} "
    f"user={PG_USER} password={PG_PASSWORD}"
)

# --- FastAPI ---
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

# --- Данные ---
DATA_DIR = BASE_DIR / "data"    # папка для входящих файлов
DATA_DIR.mkdir(exist_ok=True)

# --- Импорт ---
IMPORT_BATCH_SIZE = 10_000      # строк за одну bulk-вставку
IMPORT_ENCODING   = "ansi"      # cp1251

# --- Поставщик электроэнергии (для расчёта тарифа) ---
ELECTRICITY_PROVIDER_NAME = "АО \"ТАТЭНЕРГОСБЫТ\""
ELECTRICITY_METER_TYPES   = ["Электроснабжение", "Электроснабжение ночное"]
