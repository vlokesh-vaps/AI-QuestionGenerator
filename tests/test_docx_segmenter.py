import io
import pytest
from docx import Document
from fastapi.testclient import TestClient
from app.main import app
from app.services.docx_segmenter import DocxChapterSegmenter, TopicMarker

client = TestClient(app)


def create_sample_docx(include_toc=False, include_table=False) -> bytes:
    """Helper to create an in-memory sample DOCX for testing."""
    doc = Document()

    if include_toc:
        doc.add_heading("Table of Contents", level=1)
        doc.add_paragraph("Chapter 1: Mechanics .............. 1")
        doc.add_paragraph("Chapter 2: Thermodynamics ........ 15")
        doc.add_paragraph("Chapter 3: Electromagnetism ...... 30")

    # Chapter 1
    doc.add_heading("Chapter 1: Mechanics", level=1)
    doc.add_paragraph("Mechanics is the study of motion and forces.")
    doc.add_heading("1.1 Newton's Laws", level=2)
    doc.add_paragraph("An object in motion remains in motion unless acted upon by a net force.")

    if include_table:
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Quantity"
        table.cell(0, 1).text = "SI Unit"
        table.cell(1, 0).text = "Force"
        table.cell(1, 1).text = "Newton (N)"

    # Chapter 2
    doc.add_heading("Chapter 2: Thermodynamics", level=1)
    doc.add_paragraph("Thermodynamics is the study of heat and work.")
    doc.add_paragraph("The First Law states that energy cannot be created or destroyed.")

    # Chapter 3 (Roman numeral / Unit style)
    doc.add_heading("Unit III: Electromagnetism", level=1)
    doc.add_paragraph("Electromagnetism deals with charges and fields.")
    doc.add_paragraph("Maxwell equations describe electromagnetic phenomena.")

    # Text-only Chapter (No number)
    doc.add_heading("Quantum Foundations", level=1)
    doc.add_paragraph("Quantum mechanics explains atomic and subatomic scales.")
    doc.add_paragraph("Planck constant is fundamental to quantum phenomena.")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_marker_detection_and_parsing():
    docx_bytes = create_sample_docx(include_toc=True, include_table=True)
    markers = DocxChapterSegmenter.parse_document_markers(docx_bytes)

    assert len(markers) >= 4

    # Mechanics (Chapter 1)
    ch1 = next((m for m in markers if m.number == "1"), None)
    assert ch1 is not None
    assert "Mechanics" in ch1.title
    assert ch1.level == 1

    # Subsection 1.1
    sub1 = next((m for m in markers if m.number == "1.1"), None)
    assert sub1 is not None
    assert "Newton" in sub1.title
    assert sub1.level == 2

    # Thermodynamics (Chapter 2)
    ch2 = next((m for m in markers if m.number == "2"), None)
    assert ch2 is not None
    assert "Thermodynamics" in ch2.title

    # Unit III (Roman numeral)
    ch3 = next((m for m in markers if m.number == "III"), None)
    assert ch3 is not None
    assert "Electromagnetism" in ch3.title

    # Quantum Foundations (Text-only topic)
    ch_q = next((m for m in markers if "Quantum" in m.title), None)
    assert ch_q is not None
    assert ch_q.number is None
    assert ch_q.level == 1


def test_content_extraction_by_number():
    docx_bytes = create_sample_docx(include_toc=False, include_table=True)

    # Extract Chapter 1
    content_ch1 = DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["1"])
    assert "Mechanics is the study of motion" in content_ch1
    assert "Force | Newton (N)" in content_ch1 or "Newton (N)" in content_ch1
    assert "First Law states that energy cannot be created" not in content_ch1

    # Extract Chapter 2
    content_ch2 = DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["2"])
    assert "First Law states that energy cannot be created" in content_ch2
    assert "Mechanics is the study of motion" not in content_ch2


def test_content_extraction_by_text_topic():
    docx_bytes = create_sample_docx(include_toc=False, include_table=False)

    # Extract by exact text topic: "Thermodynamics"
    content_thermo = DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["Thermodynamics"])
    assert "Thermodynamics is the study of heat" in content_thermo
    assert "First Law" in content_thermo

    # Extract text-only chapter without numbers: "Quantum Foundations"
    content_quantum = DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["quantum"])
    assert "Planck constant is fundamental" in content_quantum
    assert "First Law" not in content_quantum


def test_api_docx_markers_endpoint():
    docx_bytes = create_sample_docx(include_toc=False, include_table=False)
    files = {"file": ("physics.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}

    res = client.post("/api/v1/exam/docx/markers", files=files)
    assert res.status_code == 200
    markers = res.json()
    assert len(markers) >= 4
    titles = [m["title"] for m in markers]
    assert any("Mechanics" in t for t in titles)
    assert any("Thermodynamics" in t for t in titles)
    assert any("Quantum" in t for t in titles)


def test_api_async_generate_with_docx():
    docx_bytes = create_sample_docx(include_toc=False, include_table=False)
    files = {"file": ("physics_textbook.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {
        "chapters": "Thermodynamics",
        "markConfig": '[{"markValue": 1, "count": 2, "isMCQ": true}]',
        "difficultyConfig": '{"easy": 50, "medium": 50, "hard": 0}'
    }

    res = client.post("/api/v1/exam-papers/generate-async", files=files, data=data)
    assert res.status_code == 202
    data = res.json()
    assert "task_id" in data
    assert data["status"] in ["PENDING", "EXTRACTING", "GENERATING", "RENDERING", "COMPLETED"]


def test_unstyled_bold_headings():
    """Test DOCX where user used bold Normal paragraphs instead of Word Heading styles."""
    doc = Document()
    p1 = doc.add_paragraph()
    r1 = p1.add_run("Chapter 5: Cell Biology")
    r1.bold = True
    doc.add_paragraph("Cells are the basic structural units of all living organisms.")

    p2 = doc.add_paragraph()
    r2 = p2.add_run("Chapter 6: Genetics")
    r2.bold = True
    doc.add_paragraph("Genetics is the study of heredity and variation in organisms.")

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    markers = DocxChapterSegmenter.parse_document_markers(docx_bytes)
    assert len(markers) == 2
    assert markers[0].number == "5"
    assert "Cell" in markers[0].title
    assert markers[1].number == "6"
    assert "Genetics" in markers[1].title

    content = DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["Chapter 5"])
    assert "Cells are the basic structural units" in content
    assert "Genetics is the study" not in content


def test_chapter_normalization_variations():
    """Verifies that 'Chapter 5', 'CHAPTER 5', 'Chapter-5', 'Chapter 5: Title', '5. Title' all resolve reliably."""
    doc = Document()
    doc.add_heading("Chapter-5: Cellular Respiration", level=1)
    doc.add_paragraph("Respiration releases energy from glucose molecules through ATP.")
    doc.add_heading("Chapter 6: Photosynthesis", level=1)
    doc.add_paragraph("Plants convert solar energy into chemical energy.")

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    markers = DocxChapterSegmenter.parse_document_markers(docx_bytes)
    assert len(markers) == 2
    assert markers[0].number == "5"
    assert markers[0].start_page >= 1
    assert markers[0].end_page >= markers[0].start_page

    # Test all variations
    for query in ["5", "Chapter 5", "CHAPTER 5", "Chapter-5", "Chapter 5: Cellular Respiration", "Cellular Respiration"]:
        matched = DocxChapterSegmenter.resolve_target_marker(query, markers)
        assert matched is not None, f"Failed to match query '{query}'"
        assert matched.number == "5"

        content = DocxChapterSegmenter.extract_chapter_content(docx_bytes, [query])
        assert "Respiration releases energy" in content
        assert "convert solar energy" not in content


def test_chapter_not_found_raises_error():
    """Ensures unsafe 30,000 character fallback is removed and ChapterNotFoundError is raised."""
    from app.services.docx_segmenter import ChapterNotFoundError
    doc = Document()
    doc.add_heading("Chapter 1: Kinematics", level=1)
    doc.add_paragraph("Motion along a straight line with uniform acceleration.")

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    with pytest.raises(ChapterNotFoundError) as exc_info:
        DocxChapterSegmenter.extract_chapter_content(docx_bytes, ["Chapter 99"])

    assert "Chapter 99" in str(exc_info.value)
    assert "Kinematics" in str(exc_info.value)


def test_max_marks_limit_validation():
    """Tests that question papers support up to 1,000 marks, but reject > 1,000 marks."""
    docx_bytes = create_sample_docx(include_toc=False, include_table=False)
    files = {"file": ("test.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}

    # Valid: 1,000 marks (100 questions of 10 marks)
    valid_data = {
        "chapters": "Mechanics",
        "markConfig": '[{"markValue": 10, "count": 100, "isMCQ": false}]',
        "difficultyConfig": '{"easy": 30, "medium": 40, "hard": 30}'
    }
    res_valid = client.post("/api/v1/exam-papers/generate-async", files=files, data=valid_data)
    assert res_valid.status_code == 202

    # Invalid: 1,010 marks (exceeds 1,000 limit)
    invalid_data = {
        "chapters": "Mechanics",
        "markConfig": '[{"markValue": 10, "count": 101, "isMCQ": false}]',
        "difficultyConfig": '{"easy": 30, "medium": 40, "hard": 30}'
    }
    files2 = {"file": ("test2.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res_invalid = client.post("/api/v1/exam-papers/generate-async", files=files2, data=invalid_data)
    assert res_invalid.status_code == 400
    assert "exceeds maximum allowed limit of 1000" in res_invalid.json()["detail"]


