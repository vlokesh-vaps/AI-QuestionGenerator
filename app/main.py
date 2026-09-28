from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.v1.router import api_router
from app.api.v1.endpoints.exam_paper import router as exam_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="""
## 🎓 AI Question Paper Generator Backend (FastAPI)

Features:
- **Web UI**: Interactive testing interface served at `/`
- **Asynchronous Task Queue (Plan 2)**: Long-running generation, background workers, progress polling, and zero-timeout handling.
- **Synchronous Direct Endpoint**: Direct drop-in compatibility for `page 6.tsx` and immediate Swagger testing.
- **Document Export**: Generates formatted **Word (.docx)** exam papers with teacher answer keys.
- **Accurate Chapter Segmentation**: Regular expression boundary extractor ported and improved from `route 7.ts`.
- **Groq LLM Acceleration**: Lightning fast question generation with difficulty controls and strict academic constraints.
    """,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory if it exists
static_dir = settings.BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount API V1
app.include_router(api_router, prefix=settings.API_V1_STR)

# Mount /api for direct backward compatibility with page 6.tsx route ('/api/exam/generate-questions')
app.include_router(exam_router, prefix="/api")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_home():
    """Serves the interactive web interface."""
    index_file = settings.BASE_DIR / "static" / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html")
    return RedirectResponse(url="/docs")

@app.get("/index", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def serve_index_redirect():
    """Redirect aliases for the index UI."""
    return RedirectResponse(url="/")

@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint checking server and Groq API key readiness."""
    has_groq = bool(settings.GROQ_API_KEY)
    return {
        "status": "healthy",
        "active_provider": settings.LLM_PROVIDER,
        "groq_configured": has_groq,
        "providers": {
            "groq": has_groq,
            "openai": bool(settings.OPENAI_API_KEY),
            "gemini": bool(settings.GEMINI_API_KEY),
            "nim": bool(settings.NIM_API_KEY)
        },
        "model": getattr(settings, f"{settings.LLM_PROVIDER.upper()}_MODEL", settings.GROQ_MODEL),
        "version": settings.VERSION
    }
