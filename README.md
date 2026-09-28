# AI Question Paper Generator (FastAPI Backend)

A production-grade, asynchronous, scalable question paper generation engine built with FastAPI, PyMuPDF, Groq LLM, and Word (.docx)/PDF document builders.

The system detects chapter/topic markers in an uploaded PDF or DOCX, lets the user
select a chapter number or title, extracts only that selected content, and creates
questions from the extracted educational content. Large documents are processed
with configured file/page limits and token-sized LLM chunks.

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and set your Groq API key:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Run the Development Server
```bash
python run.py
```
Or with Uvicorn:
```bash
uvicorn app.main:app --reload --port 8000
```

### 4. Interactive Swagger Documentation
Open your browser at:
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

---

## 🔌 API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/exam/generate-questions` | **Synchronous Direct** (Drop-in for `page 6.tsx` & quick Swagger test) |
| `POST` | `/api/v1/exam-papers/generate-async` | **Asynchronous Task** (Returns `task_id` for large textbooks) |
| `GET` | `/api/v1/tasks/{task_id}` | Poll progress (0–100%), logs, and JSON result |
| `GET` | `/api/v1/tasks/{task_id}/download/{docx\|pdf}` | Download formatted Word (.docx) or PDF document |
| `GET` | `/health` | Health & Groq configuration check |

`POST /api/v1/exam/markers` returns detected top-level chapters with confidence,
page ranges, and child topics. Wrapped PDF headings are merged using their
text geometry before filtering, and Contents-page chapter rows are preferred
when verified. The UI can use the returned chapter number/title,
or the user can enter forgiving variants such as `ch-2`, `Chatper 2`, or a fuzzy
title. Adjacent marker fragments are also tested as a combined title. Marker indexes are cached under `storage/marker_cache/` by uploaded-file
hash and are reused by generation.

At application startup, the disposable `storage/exports/`, `storage/uploads/`,
and `storage/marker_cache/` directories are cleared and recreated automatically.

`POST /api/v1/exam-papers/generate-async` accepts the existing fields plus optional
`page_start`, `page_end`, and `use_entire_document` form fields. By default it
extracts only the requested chapter(s), then token-chunks that content before LLM
generation. `use_entire_document` is opt-in and defaults to false. Scanned PDF
pages without extractable text require OCR.

---

## 🧪 Testing with cURL

### Direct Sync Test
```bash
curl -X POST "http://127.0.0.1:8000/api/exam/generate-questions" \
  -F "file=@sample_textbook.pdf" \
  -F "chapters=1" \
  -F 'markConfig=[{"markValue":1,"count":5,"isMCQ":true},{"markValue":2,"count":3,"isMCQ":false},{"markValue":5,"count":2,"isMCQ":false}]' \
  -F 'difficultyConfig={"easy":30,"medium":40,"hard":30}'
```

### Async Task & Download Test
```bash
# 1. Enqueue task
curl -X POST "http://127.0.0.1:8000/api/v1/exam-papers/generate-async" \
  -F "file=@sample_textbook.pdf" \
  -F "chapters=1, 2" \
  -F 'markConfig=[{"markValue":1,"count":5,"isMCQ":true},{"markValue":5,"count":2,"isMCQ":false}]'

# 2. Poll status (replace {task_id} with returned id)
curl "http://127.0.0.1:8000/api/v1/tasks/{task_id}"

# 3. Download Word Document
curl -O -J "http://127.0.0.1:8000/api/v1/tasks/{task_id}/download/docx"
```
