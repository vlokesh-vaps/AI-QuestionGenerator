import re
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.middleware import ReverseProxyPrefixMiddleware
from app.api.v1.router import api_router
from app.api.v1.endpoints.exam_paper import router as exam_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    root_path=settings.APPLICATION_ROOT,
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

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reverse-Proxy Prefix & Forwarded Headers Middleware (runs outermost)
app.add_middleware(
    ReverseProxyPrefixMiddleware,
    default_prefix=settings.APPLICATION_ROOT
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
def serve_home(request: Request):
    """Serves the interactive web interface with dynamic base path injection."""
    base_path = request.scope.get("root_path", "") or settings.APPLICATION_ROOT or ""
    index_file = settings.BASE_DIR / "static" / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            html = f.read()

        meta_tag = f'<meta name="app-base" content="{base_path}">'
        cfg_script = f'<script>window.__APP_CONFIG__ = Object.assign(window.__APP_CONFIG__ || {{}}, {{ basePath: "{base_path}" }}); window.__APP_BASE__ = "{base_path}";</script>'

        if '<meta name="app-base"' in html:
            html = re.sub(r'<meta\s+name=["\']app-base["\'][^>]*>', f'{meta_tag}\n    {cfg_script}', html)
        elif "<head>" in html:
            html = html.replace("<head>", f"<head>\n    {meta_tag}\n    {cfg_script}", 1)

        return HTMLResponse(content=html, media_type="text/html")

    target_docs = f"{base_path}/docs" if base_path else "/docs"
    return RedirectResponse(url=target_docs)


@app.get("/index", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def serve_index_redirect(request: Request):
    """Redirect aliases for the index UI preserving prefix."""
    base_path = request.scope.get("root_path", "") or settings.APPLICATION_ROOT or ""
    target = f"{base_path}/" if base_path else "/"
    return RedirectResponse(url=target)


@app.get("/health", tags=["Health"])
def health_check(request: Request):
    """Health check endpoint checking server, environment, and LLM readiness."""
    has_groq = bool(settings.GROQ_API_KEY)
    base_path = request.scope.get("root_path", "") or settings.APPLICATION_ROOT or ""
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
        "version": settings.VERSION,
        "application_root": base_path,
        "public_origin": settings.PUBLIC_ORIGIN,
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB
    }
