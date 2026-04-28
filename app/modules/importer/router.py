"""
importer/router.py — загрузка файлов с очередью и SSE-прогрессом.
"""
import asyncio
import time
import threading
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.db.engine import get_db, SessionLocal
from app.modules.importer.progress import get_queue, TaskProgress
from app.modules.importer.service import ImportService

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


# ── Главная страница ──────────────────────────────────────────────────────────

from fastapi import Depends

@router.get("/", response_class=HTMLResponse)
async def import_page(request: Request, db: Session = Depends(get_db)):
    from app.modules.importer.service import ImportService
    service = ImportService(db)
    history = service.get_history()
    return templates.TemplateResponse(
        "import.html",
        {"request": request, "history": history},
    )


# ── Загрузка файлов (мультивыбор) ────────────────────────────────────────────

@router.post("/upload", response_class=HTMLResponse)
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
):
    """
    Принимает один или несколько файлов.
    Каждый сохраняется на диск и ставится в очередь.
    Возвращает страницу с прогрессом всей очереди.
    """
    q = get_queue()

    for file in files:
        filename = file.filename or "unknown"
        tmp_path = DATA_DIR / f"_upload_{int(time.time() * 1000)}_{filename}.tmp"

        with open(tmp_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        file_size = tmp_path.stat().st_size
        rows_est  = max(int(file_size / 250), 100_000)

        task = TaskProgress(
            task_id=str(__import__('uuid').uuid4()),
            filename=filename,
            rows_total_estimate=rows_est,
        )

        # Замыкание для воркера — каждый файл получает свой tmp_path
        def make_runner(tp, fn):
            def runner(t: TaskProgress):
                db = SessionLocal()
                try:
                    service = ImportService(db)
                    result  = service._run_import(
                        tp, fn, time.time(),
                        service._make_empty_result(fn),
                        progress=t,
                    )
                    if result.success:
                        t.finish()
                    else:
                        t.fail(result.error_message)
                except Exception as e:
                    import traceback
                    print(f"[IMPORT ERROR] {fn}: {e}")
                    traceback.print_exc()
                    t.fail(str(e))
                finally:
                    db.close()
                    if tp.exists():
                        tp.unlink()
            return runner

        q.enqueue(task, tmp_path, filename, make_runner(tmp_path, filename))

    return templates.TemplateResponse(
        "import_progress.html",
        {"request": request},
    )


# ── SSE очереди ───────────────────────────────────────────────────────────────

@router.get("/progress/queue")
async def queue_progress_sse(request: Request):
    """SSE: шлёт состояние всей очереди каждую секунду."""

    async def event_stream():
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                break

            q = get_queue()
            q.cleanup_done()
            tasks = q.get_all_tasks()

            html = _render_queue_html(tasks)
            yield f"data: {html.replace(chr(10), ' ')}\n\n"

            # Если все завершены — ещё 3 секунды и закрываем
            all_done = all(t.done for t in tasks) if tasks else True
            if all_done:
                idle_ticks += 1
                if idle_ticks >= 3:
                    break
            else:
                idle_ticks = 0

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Рендер HTML очереди ───────────────────────────────────────────────────────

def _render_queue_html(tasks: list) -> str:
    if not tasks:
        return '<p class="text-muted">Очередь пуста.</p>'

    parts = []
    for t in tasks:
        parts.append(_render_task_card(t))
    return "".join(parts)


def _render_task_card(t: TaskProgress) -> str:
    if t.phase == "queued":
        badge  = f'<span class="badge bg-secondary">В очереди #{t.queue_pos}</span>'
        bar    = '<div class="progress mt-2" style="height:20px"><div class="progress-bar bg-secondary" style="width:0%"></div></div>'
        detail = ""

    elif t.phase == "error":
        badge  = '<span class="badge bg-danger">Ошибка</span>'
        bar    = '<div class="progress mt-2" style="height:20px"><div class="progress-bar bg-danger" style="width:100%"></div></div>'
        detail = f'<div class="text-danger small mt-1">{t.error_message}</div>'

    elif t.phase == "done":
        badge  = f'<span class="badge bg-success">Готово — {t.elapsed} сек</span>'
        bar    = '<div class="progress mt-2" style="height:20px"><div class="progress-bar bg-success" style="width:100%">100%</div></div>'
        detail = f'<div class="text-muted small mt-1">Загружено строк: {t.rows_parsed:,}</div>'

    else:
        badge  = f'<span class="badge bg-primary">Импорт...</span>'
        rows_s = f"{t.rows_parsed:,} строк" if t.rows_parsed else ""
        time_s = f"{t.elapsed} сек"
        bar    = (
            f'<div class="progress mt-2" style="height:20px">'
            f'<div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" '
            f'style="width:{t.pct}%">{t.pct}%</div></div>'
        )
        detail = f'<div class="text-muted small mt-1">{t.phase_label} &nbsp; {rows_s} &nbsp; {time_s}</div>'

    return (
        f'<div class="card mb-2">'
        f'<div class="card-body py-2 px-3">'
        f'<div class="d-flex justify-content-between align-items-center">'
        f'<span class="fw-semibold">{t.filename}</span>{badge}'
        f'</div>'
        f'{bar}{detail}'
        f'</div></div>'
    )
