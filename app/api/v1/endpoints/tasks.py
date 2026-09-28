from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.core.config import settings
from app.core.task_store import task_store
from app.schemas.task_state import TaskResponse

router = APIRouter()

@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="Poll task status & result")
def get_task_status(task_id: str):
    """
    Polls the asynchronous task progress, state, logs, and generated paper.
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ID not found")
    return task

@router.get("/tasks/{task_id}/download/{file_format}", summary="Download generated Word (.docx)")
def download_generated_file(task_id: str, file_format: str = "docx"):
    """
    Download the generated file artifact: 'docx'.
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task ID not found")

    fmt = file_format.lower().strip()
    if fmt != "docx":
        raise HTTPException(status_code=400, detail="Invalid format. Only 'docx' format is generated.")

    file_path = settings.EXPORTS_DIR / f"{task_id}.docx"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Generated DOCX file not found for this task")

    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    filename = f"Exam_Paper_{task_id[:8]}.docx"
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename
    )

