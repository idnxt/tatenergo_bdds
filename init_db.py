"""
init_db.py — первичная инициализация базы данных.
Запускается из start.bat при первом старте (если БД ещё не создана).

Что делает:
  1. Создаёт роль и базу данных если не существует
  2. Применяет миграции из app/db/migrations/ по порядку
"""
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import PG_PORT, PG_DB, PG_USER, PG_PASSWORD

MIGRATIONS_DIR = Path(__file__).parent / "app" / "db" / "migrations"


def wait_for_pg(retries: int = 10, delay: float = 1.5) -> bool:
    """Ждём, пока PostgreSQL поднимется после pg_ctl start."""
    for i in range(retries):
        try:
            conn = psycopg2.connect(
                host="localhost", port=PG_PORT,
                dbname="postgres", user="postgres",
            )
            conn.close()
            return True
        except psycopg2.OperationalError:
            print(f"  PostgreSQL не готов, ожидание... ({i+1}/{retries})")
            time.sleep(delay)
    return False


def create_role_and_db():
    """Создаём роль и БД от имени суперпользователя postgres."""
    conn = psycopg2.connect(
        host="localhost", port=PG_PORT,
        dbname="postgres", user="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Роль
    cur.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (PG_USER,)
    )
    if not cur.fetchone():
        cur.execute(
            f"CREATE ROLE {PG_USER} WITH LOGIN PASSWORD %s", (PG_PASSWORD,)
        )
        print(f"  Роль '{PG_USER}' создана.")

    # База данных
    cur.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (PG_DB,)
    )
    if not cur.fetchone():
        cur.execute(
            f'CREATE DATABASE "{PG_DB}" OWNER {PG_USER} ENCODING \'UTF8\''
        )
        print(f"  База данных '{PG_DB}' создана.")
    else:
        print(f"  База данных '{PG_DB}' уже существует.")

    cur.close()
    conn.close()


def apply_migrations():
    """Применяем все .sql файлы из migrations/ по порядку."""
    conn = psycopg2.connect(
        host="localhost", port=PG_PORT,
        dbname=PG_DB, user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # Таблица версий миграций
    cur.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT now()
        )
    """)
    conn.commit()

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print("  Нет файлов миграций.")
        conn.close()
        return

    for mf in migration_files:
        cur.execute("SELECT 1 FROM _migrations WHERE filename = %s", (mf.name,))
        if cur.fetchone():
            print(f"  Пропуск (уже применена): {mf.name}")
            continue

        print(f"  Применяем миграцию: {mf.name}")
        sql = mf.read_text(encoding="utf-8")
        cur.execute(sql)
        cur.execute(
            "INSERT INTO _migrations (filename) VALUES (%s)", (mf.name,)
        )
        conn.commit()
        print(f"  ✓ {mf.name}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    print("=== Инициализация базы данных tatenergo_bdds ===")

    print("Ожидание PostgreSQL...")
    if not wait_for_pg():
        print("ОШИБКА: PostgreSQL не запустился за отведённое время.")
        sys.exit(1)

    print("Создание роли и базы данных...")
    create_role_and_db()

    print("Применение миграций...")
    apply_migrations()

    print("=== Инициализация завершена ===")
