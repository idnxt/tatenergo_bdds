"""
Подключение к PostgreSQL.
engine     — SQLAlchemy engine (для ORM / миграций)
get_db()   — FastAPI dependency (сессия на запрос)
raw_conn() — контекстный менеджер для psycopg2 (bulk COPY)
"""
from contextlib import contextmanager

import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL, PG_DSN

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=0,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


# FastAPI dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Прямое подключение psycopg2 для COPY FROM
@contextmanager
def raw_conn():
    conn = psycopg2.connect(PG_DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_connection() -> bool:
    """Проверка соединения при старте приложения."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"[DB] Ошибка подключения: {e}")
        return False
