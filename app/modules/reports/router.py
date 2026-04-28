"""
reports/router.py — роуты для отчётов.
Пока реализован один отчёт: сводка по периоду импорта.
Новые отчёты добавляются сюда как дополнительные роуты.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.db.engine import get_db
from app.modules.reports.service import ReportService

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def reports_index(request: Request, db: Session = Depends(get_db)):
    """Список доступных отчётов и загруженных периодов."""
    service = ReportService(db)
    periods = service.get_periods()
    return templates.TemplateResponse(
        "reports/index.html",
        {"request": request, "periods": periods},
    )


@router.get("/summary/{import_id}", response_class=HTMLResponse)
async def report_summary(
    import_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Отчёт-сводка по выбранному периоду."""
    service = ReportService(db)
    data    = service.get_summary(import_id)
    if not data:
        raise HTTPException(status_code=404, detail="Период не найден")
    return templates.TemplateResponse(
        "reports/summary.html",
        {"request": request, **data},
    )