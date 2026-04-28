"""
progress.py — очередь импорта и хранилище прогресса.

Архитектура:
  - ImportQueue: глобальная очередь файлов, один воркер-поток
  - TaskProgress: прогресс одного файла (текущего)
  - Браузер подписывается на SSE /import/progress/queue
    и получает обновления по всей очереди целиком
"""
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable


# ─── Прогресс одного файла ────────────────────────────────────────────────────

@dataclass
class TaskProgress:
    task_id:   str
    filename:  str
    queue_pos: int = 0          # позиция в очереди (0 = выполняется)
    started_at: float = field(default_factory=time.time)

    phase:       str = "queued"
    phase_label: str = "В очереди..."
    pct:         int = 0

    rows_parsed:          int = 0
    rows_total_estimate:  int = 0

    error_message: str  = ""
    done:          bool = False

    def update(self, phase: str, label: str, pct: int, rows: int = 0):
        self.phase       = phase
        self.phase_label = label
        self.pct         = pct
        if rows:
            self.rows_parsed = rows

    def finish(self):
        self.phase       = "done"
        self.phase_label = "Завершено"
        self.pct         = 100
        self.done        = True

    def fail(self, msg: str):
        self.phase         = "error"
        self.phase_label   = "Ошибка"
        self.error_message = msg
        self.done          = True

    def start_processing(self):
        self.phase       = "starting"
        self.phase_label = "Подготовка..."
        self.queue_pos   = 0
        self.started_at  = time.time()

    @property
    def elapsed(self) -> int:
        return int(time.time() - self.started_at)


# ─── Глобальная очередь ───────────────────────────────────────────────────────

@dataclass
class QueueItem:
    task:     TaskProgress
    tmp_path: object          # Path
    filename: str
    runner:   Callable        # функция импорта


class ImportQueue:
    """
    Единственный экземпляр на процесс.
    Воркер-поток берёт задачи по одной и выполняет синхронно.
    """

    def __init__(self):
        self._q:      queue.Queue  = queue.Queue()
        self._tasks:  dict         = {}   # task_id → TaskProgress
        self._lock:   threading.Lock = threading.Lock()
        self._worker: threading.Thread = threading.Thread(
            target=self._run_worker, daemon=True
        )
        self._worker.start()

    def enqueue(self, task: TaskProgress, tmp_path, filename: str,
                runner: Callable) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            # Обновляем позиции всех ожидающих задач
            waiting = [t for t in self._tasks.values()
                       if t.phase in ("queued", "starting") and t.task_id != task.task_id]
            task.queue_pos = len(waiting) + 1
        self._q.put(QueueItem(task=task, tmp_path=tmp_path,
                               filename=filename, runner=runner))

    def get_all_tasks(self) -> list[TaskProgress]:
        """Возвращает все задачи в порядке добавления (активные + ожидающие + завершённые)."""
        with self._lock:
            return list(self._tasks.values())

    def get_task(self, task_id: str) -> Optional[TaskProgress]:
        return self._tasks.get(task_id)

    def cleanup_done(self) -> None:
        """Удаляет завершённые задачи старше 60 секунд."""
        now = time.time()
        with self._lock:
            to_del = [tid for tid, t in self._tasks.items()
                      if t.done and (now - t.started_at) > 60]
            for tid in to_del:
                del self._tasks[tid]

    def _run_worker(self):
        while True:
            item: QueueItem = self._q.get()
            try:
                item.task.start_processing()
                item.runner(item.task)
            except Exception as e:
                item.task.fail(str(e))
            finally:
                # Обновляем позиции оставшихся в очереди
                with self._lock:
                    pos = 1
                    for t in self._tasks.values():
                        if t.phase == "queued":
                            t.queue_pos = pos
                            pos += 1
                self._q.task_done()


# Единственный экземпляр очереди
_import_queue = ImportQueue()


def get_queue() -> ImportQueue:
    return _import_queue
