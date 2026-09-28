from fastapi import APIRouter
from app.api.v1.endpoints import exam_paper, tasks, config

api_router = APIRouter()

# Mount endpoints
api_router.include_router(exam_paper.router, tags=["Exam Paper Generation"])
api_router.include_router(tasks.router, tags=["Async Task & File Downloads"])
api_router.include_router(config.router, tags=["LLM Configuration & Diagnostics"])
