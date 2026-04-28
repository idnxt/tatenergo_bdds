"""
importer/router.py — HTTP-роуты для загрузки файлов.
Вся тяжёлая логика — в importer/service.py.
"""
from fastapi import APIRouter, Request, UploadFile, File, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.db.engine import get_db
from app.modules.importer.service import ImportService

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def import_page(request: Request, db: Session = Depends(get_db)):
    """Страница загрузки файла + история импортов."""
    service = ImportService(db)
    history = service.get_history()
    return templates.TemplateResponse(
        "import.html",
        {"request": request, "history": history},
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Принимает файл, запускает синхронный импорт, возвращает результат.
    HTMX получает HTML-фрагмент с итогами.
    """
    service = ImportService(db)
    result  = await service.import_file(file)

    return templates.TemplateResponse(
        "partials/import_result.html",
        {"request": request, "result": result},
    )
