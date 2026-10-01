# AI Question Paper Generator - Agent Guide

This guide explains the project structure and the recommended workflow for coding agents and contributors. Treat the existing code and tests as the source of truth; update this guide when the architecture or commands change.

## README maintenance

Before making code changes, read the relevant `README.md` files (starting with the root `README.md`) to understand the documented behavior and setup. When a change affects user-visible behavior, API routes, configuration, installation, or run/test commands, update the relevant README in the same change so the documentation stays accurate. Do not make unrelated README edits, and do not document secrets or machine-specific values.

## Project purpose

This repository contains a Python/FastAPI backend for generating exam question papers from uploaded DOCX or PDF textbooks. It extracts selected chapter content, sends it to a configured language-model provider, validates the generated questions, and can build a downloadable DOCX paper.

## Technology

- Python with FastAPI and Uvicorn
- Pydantic / pydantic-settings for request schemas and configuration
- PyMuPDF and python-docx for PDF and DOCX handling
- Groq, OpenAI, Gemini, or NVIDIA NIM through the LLM engine
- pytest for automated tests

## Repository map

| Path | Responsibility |
|---|---|
| `run.py` | Starts the Uvicorn development server using `HOST`, `PORT`, and `DEBUG`. |
| `Dockerfile` / `.dockerignore` | Builds and packages the API image for container deployment on port 8050. |
| `app/main.py` | Creates the FastAPI app, configures CORS/static UI, mounts routers, and exposes health status. |
| `app/api/v1/router.py` | Collects versioned API endpoint routers. |
| `app/api/v1/endpoints/exam_paper.py` | Validates upload/configuration, discovers markers, and coordinates synchronous or background paper generation. |
| `app/api/v1/endpoints/tasks.py` | Reads asynchronous task progress/results and serves generated DOCX files. |
| `app/api/v1/endpoints/config.py` | Reads and updates LLM provider configuration and tests provider connectivity. |
| `app/core/config.py` | Environment-backed settings and storage directory initialization. |
| `app/core/task_store.py` | In-memory task lifecycle/status storage. |
| `app/core/logger.py` / `exceptions.py` | Shared logging and domain exceptions. |
| `app/schemas/` | Pydantic request, response, exam-paper, and task models. |
| `app/services/text_extractor.py` | Validates files and provides full-document extraction when needed; generation should prefer selected-content extraction. |
| `app/services/chapter_segmenter.py` | Finds and extracts chapter content from PDFs. |
| `app/services/docx_segmenter.py` | Finds and extracts headings/chapters from DOCX files. |
| `app/services/marker_cache.py` | Caches marker indexes by uploaded-file hash under `storage/marker_cache/`. |
| `app/services/token_chunker.py` | Splits content into token-budget-aware chunks for model calls. |
| `app/services/llm_engine.py` and `llm_groq_engine.py` | Coordinates model providers and question generation. |
| `app/services/question_validator.py` / `content_sanitizer.py` | Checks and normalizes generated content. |
| `app/services/docx_generator.py` | Builds the final Word question paper. |
| `static/` | Browser-based project interface. |
| `storage/uploads/`, `storage/exports/` | Runtime upload/export directories; do not commit generated user documents. |
| `tests/` | API, extraction/segmentation, chunking, and content pipeline tests. |

## Main request flows

### Synchronous generation

1. `POST /api/exam/generate-questions` accepts a DOCX/PDF, chapter selection, mark configuration, difficulty distribution, and optional provider.
2. The endpoint validates the file and parses configuration.
3. The appropriate chapter segmenter extracts the requested source content.
4. `LLMExamEngine` generates and validates the paper, using token-aware chunking as needed.
5. The endpoint returns the `QuestionPaper` JSON response.

### Asynchronous generation

1. `POST /api/v1/exam-papers/generate-async` validates the upload/config and creates a task.
2. FastAPI background work extracts the selected chapters, generates questions, and writes a DOCX under `storage/exports/`.
3. Poll `GET /api/v1/tasks/{task_id}` for status/progress/result.
4. Download the DOCX from `GET /api/v1/tasks/{task_id}/download/docx`.

### Marker discovery

`POST /api/v1/exam/markers` (also available as `/api/v1/exam/docx/markers`) parses the uploaded DOCX/PDF and returns detected chapter/topic markers. The parser selected depends on the uploaded filename extension.

### Required chapter-selection behavior

The central user flow is:

1. Upload a PDF or DOCX textbook.
2. Discover chapter/topic markers through `/api/v1/exam/markers`.
3. Let the user enter or select a chapter number or title, such as `2`, `Chapter 2`, or `Thermodynamics`.
4. Extract only the selected chapter/topic content.
5. Pass the extracted content to the LLM engine for question-paper generation.
6. Validate, deduplicate, and compile the generated paper into a DOCX.

The async generation pipeline must not call `TextExtractor.extract_document` merely to prepare the selected chapter. For large files, validate the upload and use `ChapterSegmenter.extract_pdf_chapter_content` or `DocxChapterSegmenter.extract_chapter_content` directly. These functions must fail explicitly when the requested chapter cannot be found or contains insufficient educational content; never silently use unrelated document text as a fallback.

The LLM engine is responsible for token-aware chunking of the selected chapter. Do not send a complete large textbook to an LLM request. Preserve the configured file/page limits and the `MAX_INPUT_TOKENS`/`SAFE_INPUT_TOKENS` safeguards.

PDF discovery uses this priority order: embedded outline/bookmarks, verified Contents-page rows, font/weight heading evidence, then conservative explicit Chapter/Unit regex. The public markers endpoint returns top-level chapters with confidence, page ranges, and child topics; exercise/question lines must not become chapters. Printed Contents page numbers must be verified against title text before they are used as physical PDF pages.

Font-based PDF detection must merge consecutive same-style, similarly aligned lines using their bounding boxes before applying fragment/sentence filters. Numbered headings with one numeric component are chapters; dotted numbers such as `4.2` and `4.2.2` are child topics. Target matching normalizes punctuation and whitespace, tries adjacent same-page marker fragments, and uses the fuzzy-match threshold without silently selecting ambiguous content.

Generation accepts optional `page_start`, `page_end`, and `use_entire_document` form fields. Page ranges are validated before task creation. Failed tasks use status `FAILED` with progress `0`; clients must not render a full progress bar for a failed task or display the same error twice.

Startup calls `reset_runtime_storage()` and clears/recreates only `storage/exports/`, `storage/uploads/`, and `storage/marker_cache/`. These directories are disposable runtime state; never put source files or persistent user data there.

## Local setup and commands

Run commands from the repository root.

```powershell
# Create and activate a virtual environment if needed
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure provider credentials in a local .env file
Copy-Item .env.example .env

# Start the server
python run.py

# Run the test suite
python -m pytest
```

`pypdf` is required by the API tests and is included in `requirements.txt`. Run commands with the project virtual environment active (`.venv\Scripts\Activate.ps1` on Windows); using a different global Python installation can produce misleading missing-module errors.

### Docker setup

```powershell
docker build -t ai-question-generator:latest .
docker run --rm --name ai-question-generator --env-file .env -p 8050:8050 ai-question-generator:latest
```

The image uses Python 3.11, runs as non-root `appuser`, excludes `.env` and runtime storage contents, and clears/recreates disposable runtime storage on startup.

The API documentation is available at `http://127.0.0.1:8050/docs` when the server is running. Configure only the provider credentials you need. Never put real API keys in source, tests, documentation, or commits; do not read or disclose local `.env` values.

## Coding workflow

1. **Understand the full path first.** Read the relevant README files, then the endpoint, the called service(s), the related schema, and any relevant tests before editing. Use the file map above to trace a request end-to-end.
2. **Keep responsibilities separated.** HTTP parsing/response handling belongs in endpoints; document processing and generation belong in services; validation/serialization belongs in schemas.
3. **Preserve API compatibility.** Keep established routes, request field names, response shapes, and task status transitions unless the change explicitly requires an API change. Update the relevant README files and tests for intentional changes.
4. **Validate inputs and failures explicitly.** Use the existing domain exceptions, FastAPI `HTTPException`, and logging patterns. Do not silently substitute unrelated content or report success after a failed operation.
5. **Respect resource limits.** Follow configured file/page/mark limits and token budgets. Avoid loading extra document data or making unbounded model requests.
6. **Keep secrets and generated artifacts out of changes.** Do not modify `.env` with credentials, and do not add files from `.venv/`, caches, or runtime storage exports.
7. **Test the affected behavior.** Prefer the narrowest relevant test file(s), then run `python -m pytest` when changes cross components. Add regression tests for changed behavior.
8. **Summarize the handoff.** State what changed and any limitations or relevant test outcome; do not claim unrun tests passed.

## Existing API surface

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/exam/generate-questions` | Synchronous generation; compatibility route. |
| `POST` | `/api/v1/exam-papers/generate-async` | Start background generation. |
| `GET` | `/api/v1/tasks/{task_id}` | Poll task progress and result. |
| `GET` | `/api/v1/tasks/{task_id}/download/docx` | Download generated DOCX. |
| `POST` | `/api/v1/exam/markers` | Discover DOCX/PDF chapter and topic markers. |
| `GET` | `/api/v1/config/llm` | Read configured provider/model status. |
| `POST` | `/api/v1/config/llm` | Update provider settings. |
| `POST` | `/api/v1/config/llm/test` | Test a provider connection. |
| `GET` | `/health` | Check server and provider configuration status. |
