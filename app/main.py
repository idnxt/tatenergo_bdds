"""
main.py — точка входа FastAPI.
Роуты разбиты по модулям, здесь только сборка приложения и корневые маршруты.
"""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.db.engine import check_connection
from app.config import APP_HOST, APP_PORT

# Подключаем роуты модулей
from app.modules.importer.router import router as importer_router
from app.modules.reports.router import router as reports_router
from app.modules.reports.provider_router import router as provider_router
from app.modules.reports.account_detail_router import router as account_detail_router
from app.modules.reports.region_meter_analysis_router import router as region_meter_analysis_router

BASE_DIR   = Path(__file__).resolve().parent
templates  = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(
    title="tatenergo_bdds",
    description="Аналитика начислений ЖКУ",
    version="0.1.0",
    docs_url="/api/docs",
)

app.include_router(importer_router, prefix="/import", tags=["import"])
app.include_router(reports_router, prefix="/reports", tags=["reports"])
app.include_router(provider_router, prefix="/reports", tags=["reports"])
app.include_router(account_detail_router, prefix="/reports", tags=["reports"])
app.include_router(region_meter_analysis_router, prefix="/reports", tags=["reports"])


@app.on_event("startup")
async def on_startup():
    if not check_connection():
        raise RuntimeError("Cannot connect to PostgreSQL. Check pgdata and start.bat.")
    _cleanup_incomplete_imports()
    print(f"[OK] DB connected. App available at http://{APP_HOST}:{APP_PORT}")


def _cleanup_incomplete_imports():
    """
    Удаляет записи import_log у которых row_count IS NULL —
    признак незавершённого импорта (упал после INSERT но до финального UPDATE).
    """
    from app.db.engine import raw_conn
    try:
        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM import_log WHERE row_count IS NULL")
            stale = [r[0] for r in cur.fetchall()]
            if not stale:
                return
            print(f"[CLEANUP] Found {len(stale)} incomplete import(s): {stale}")
            for import_id in stale:
                cur.execute("DELETE FROM tariff_calc WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM meter_readings WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM charge_providers WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM charges WHERE import_id=%s", (import_id,))
                cur.execute("DELETE FROM import_log WHERE id=%s", (import_id,))
            conn.commit()
            print(f"[CLEANUP] Removed {len(stale)} incomplete import(s).")
    except Exception as e:
        print(f"[WARN] Cleanup failed: {e}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница — дашборд с загруженными периодами."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.on_event("startup")
async def on_startup():
    if not check_connection():
        raise RuntimeError("Cannot connect to PostgreSQL. Check pgdata and start.bat.")
    _cleanup_incomplete_imports()
    print(f"[OK] DB connected. App available at http://{APP_HOST}:{APP_PORT}")


def _cleanup_incomplete_imports():
    """
    Удаляет записи import_log у которых row_count IS NULL —
    признак незавершённого импорта (упал после INSERT но до финального UPDATE).
    """
    from app.db.engine import raw_conn
    try:
        with raw_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM import_log WHERE row_count IS NULL")
            stale = [r[0] for r in cur.fetchall()]
            if not stale:
                return
            print(f"[CLEANUP] Found {len(stale)} incomplete import(s): {stale}")
            for import_id in stale:
                cur.execute("DELETE FROM tariff_calc WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM meter_readings WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM charge_providers WHERE charge_id IN (SELECT id FROM charges WHERE import_id=%s)", (import_id,))
                cur.execute("DELETE FROM charges WHERE import_id=%s", (import_id,))
                cur.execute("DELETE FROM import_log WHERE id=%s", (import_id,))
            conn.commit()
            print(f"[CLEANUP] Removed {len(stale)} incomplete import(s).")
    except Exception as e:
        print(f"[WARN] Cleanup failed: {e}")
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница — дашборд с загруженными периодами."""
    return templates.TemplateResponse("index.html", {"request": request})
