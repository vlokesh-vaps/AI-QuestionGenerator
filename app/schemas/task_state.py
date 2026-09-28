from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from app.schemas.exam_paper import QuestionPaper

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    GENERATING = "GENERATING"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: str = "Task initialized"
    result: Optional[QuestionPaper] = None
    docx_download_url: Optional[str] = None
    error: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
