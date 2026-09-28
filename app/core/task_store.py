import uuid
from typing import Dict, Optional, List
from threading import Lock
from app.schemas.task_state import TaskResponse, TaskStatus

class TaskStore:
    def __init__(self):
        self._tasks: Dict[str, TaskResponse] = {}
        self._lock = Lock()

    def create_task(self) -> str:
        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = TaskResponse(
                task_id=task_id,
                status=TaskStatus.PENDING,
                progress=5,
                message="Task enqueued in queue",
                logs=[f"Task {task_id} initialized."]
            )
        return task_id

    def get_task(self, task_id: str) -> Optional[TaskResponse]:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result=None,
        docx_download_url: Optional[str] = None,
        error: Optional[str] = None,
        log_message: Optional[str] = None
    ):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if result is not None:
                task.result = result
            if docx_download_url is not None:
                task.docx_download_url = docx_download_url
            if error is not None:
                task.error = error
            if log_message:
                task.logs.append(log_message)


task_store = TaskStore()
