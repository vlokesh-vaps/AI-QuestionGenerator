import pytest
import pymupdf
from app.services.chapter_segmenter import ChapterSegmenter
from app.core.exceptions import ChapterNotFoundError, InsufficientSourceContentError


def create_sample_pdf_with_chapters() -> bytes:
    """
    Creates a 50-page PDF document:
    - Page 1: Chapter 1: Foundations of Physics
    - Pages 2-11: Chapter 1 substantive educational content
    - Page 12: Chapter 2: Forces and Motion
    - Pages 13-34: Chapter 2 substantive educational content (Newton's laws, gravitation, velocity, momentum)
    - Page 35: Chapter 3: Thermodynamics
    - Pages 36-50: Chapter 3 substantive educational content
    """
    doc = pymupdf.open()
    for i in range(50):
        p = doc.new_page()
        page_num = i + 1
        if page_num == 1:
            p.insert_text((50, 50), "Chapter 1: Foundations of Physics\nPhysics is the systematic study of the physical world and the laws of nature.")
        elif page_num == 12:
            p.insert_text((50, 50), "Chapter 2: Forces and Motion\nMotion is the continuous change in the position of a body relative to a reference point.\nKinematics describes motion without considering the forces causing it.")
        elif page_num == 13:
            p.insert_text((50, 50), "Section 2.1: Newton's Laws of Motion\nNewton's first law states that an object at rest stays at rest unless acted on by an external net force.\nNewton's second law states that force equals mass times acceleration: F = ma.\nNewton's third law states that for every action there is an equal and opposite reaction.")
        elif page_num == 20:
            p.insert_text((50, 50), "Section 2.2: Universal Gravitation and Planetary Motion\nGravitation is the attractive force that acts between all masses in the universe.\nThe gravitational force is directly proportional to the product of masses and inversely proportional to the square of distance.")
        elif page_num == 34:
            p.insert_text((50, 50), "Summary of Chapter 2: Forces and Motion\nMomentum is the product of mass and velocity. Conservation of linear momentum applies in closed systems.\nPractice questions on kinematics and dynamics.")
        elif page_num == 35:
            p.insert_text((50, 50), "Chapter 3: Thermodynamics and Heat Transfer\nThermodynamics is the branch of physics that deals with heat, work, and temperature.\nThe zeroth law defines thermal equilibrium.")
        else:
            p.insert_text((50, 50), f"Page {page_num} substantive text. Detailed physics principles, mathematical formulas, and scientific explanations.")

    doc.set_toc([
        [1, "Chapter 1: Foundations of Physics", 1],
        [1, "Chapter 2: Forces and Motion", 12],
        [2, "Section 2.1: Newton's Laws of Motion", 13],
        [2, "Section 2.2: Universal Gravitation", 20],
        [1, "Chapter 3: Thermodynamics and Heat Transfer", 35]
    ])

    return doc.write()


def test_pdf_markers_page_ranges():
    pdf_bytes = create_sample_pdf_with_chapters()
    markers = ChapterSegmenter.parse_pdf_markers(pdf_bytes)

    ch1 = next((m for m in markers if m.number == "1"), None)
    assert ch1 is not None
    assert ch1.start_page == 1
    assert ch1.end_page == 11  # Ends before Chapter 2 (page 12)

    ch2 = next((m for m in markers if m.number == "2"), None)
    assert ch2 is not None
    assert ch2.start_page == 12
    assert ch2.end_page == 34  # Ends before Chapter 3 (page 35)

    ch3 = next((m for m in markers if m.number == "3"), None)
    assert ch3 is not None
    assert ch3.start_page == 35
    assert ch3.end_page == 50  # Ends at total pages (50)


def test_pdf_chapter_2_full_range_extraction(caplog):
    import logging
    pdf_bytes = create_sample_pdf_with_chapters()

    with caplog.at_level(logging.INFO):
        content = ChapterSegmenter.extract_pdf_chapter_content(pdf_bytes, ["2"])

    # Must contain substantive text from page 12, page 13, page 20, and page 34
    assert "Motion is the continuous change" in content
    assert "Newton's first law states" in content
    assert "Universal Gravitation" in content
    assert "Conservation of linear momentum" in content

    # Must NOT contain Chapter 3 content from page 35
    assert "Thermodynamics is the branch of physics" not in content
    assert "zeroth law defines thermal equilibrium" not in content

    # Check extracted content is substantial (thousands of characters, NOT 35 characters)
    assert len(content) > 1000

    # Verify log output matches specification
    log_text = caplog.text
    assert "Selected chapter 2" in log_text or "Selected chapter '2'" in log_text
    assert "start page 12" in log_text
    assert "next chapter" in log_text
    assert "page 35" in log_text
    assert "12–34" in log_text or "12-34" in log_text
    assert "total pages extracted 23" in log_text


def test_pdf_last_chapter_extraction_to_end_of_document(caplog):
    import logging
    pdf_bytes = create_sample_pdf_with_chapters()

    with caplog.at_level(logging.INFO):
        content = ChapterSegmenter.extract_pdf_chapter_content(pdf_bytes, ["3"])

    assert "Thermodynamics is the branch of physics" in content
    assert len(content) > 500

    log_text = caplog.text
    assert "start page 35" in log_text
    assert "35–50" in log_text or "35-50" in log_text
    assert "total pages extracted 16" in log_text


def test_pdf_insufficient_content_raises_error():
    """Verifies that an empty or near-empty chapter raises InsufficientSourceContentError."""
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Chapter 1: Empty Topic")  # only title, no educational text
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Chapter 2: Substantive Physics\nEnergy can neither be created nor destroyed in an isolated system.\nThermodynamics governs heat engines and refrigerators across thermal cycles.")

    doc.set_toc([
        [1, "Chapter 1: Empty Topic", 1],
        [1, "Chapter 2: Substantive Physics", 2]
    ])
    pdf_bytes = doc.write()

    with pytest.raises(InsufficientSourceContentError):
        ChapterSegmenter.extract_pdf_chapter_content(pdf_bytes, ["1"])


def test_pdf_chapter_not_found_raises_error():
    pdf_bytes = create_sample_pdf_with_chapters()
    with pytest.raises(ChapterNotFoundError):
        ChapterSegmenter.extract_pdf_chapter_content(pdf_bytes, ["99"])
