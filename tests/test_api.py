import io
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from app.main import app

client = TestClient(app)

def test_health_check():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "groq_configured" in data

def test_serve_ui_home():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "AI Question Paper Generator" in res.text
    assert "Processing Engine Mode" not in res.text
    assert "/api/v1/exam-papers/generate-async" in res.text

def test_ui_redirect_aliases():
    res_index = client.get("/index", follow_redirects=False)
    assert res_index.status_code in [302, 307]
    assert res_index.headers["location"] == "/"

    res_html = client.get("/index.html", follow_redirects=False)
    assert res_html.status_code in [302, 307]
    assert res_html.headers["location"] == "/"

def test_swagger_docs():
    res = client.get("/docs")
    assert res.status_code == 200

def test_async_task_enqueue():
    # Create minimal PDF
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    pdf_buf = io.BytesIO()
    writer.write(pdf_buf)
    pdf_bytes = pdf_buf.getvalue()

    files = {"file": ("test.pdf", pdf_bytes, "application/pdf")}
    data = {
        "chapters": "1",
        "markConfig": '[{"markValue": 1, "count": 2, "isMCQ": true}]',
        "difficultyConfig": '{"easy": 50, "medium": 50, "hard": 0}'
    }

    res = client.post("/api/v1/exam-papers/generate-async", files=files, data=data)
    assert res.status_code == 202
    task_data = res.json()
    assert "task_id" in task_data
    task_id = task_data["task_id"]

    # Poll task
    poll_res = client.get(f"/api/v1/tasks/{task_id}")
    assert poll_res.status_code == 200
    assert poll_res.json()["task_id"] == task_id
