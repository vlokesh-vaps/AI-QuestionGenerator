import pytest
from app.services.chapter_segmenter import ChapterSegmenter

def test_chapter_boundary_extraction():
    sample_text = """
    PREFACE
    Welcome to this book.

    Chapter 1. Introduction to Physics
    Physics is the study of matter, energy, and the interactions between them.
    Newton formulated laws of motion.

    Chapter 2. Thermodynamics
    Thermodynamics deals with heat, work, and temperature.
    First law states conservation of energy.

    Chapter 3. Electromagnetism
    Maxwell equations describe electromagnetism.
    """

    content_ch1 = ChapterSegmenter.extract_chapter_content(sample_text, ["1"])
    assert "Introduction to Physics" in content_ch1
    assert "Newton formulated laws of motion" in content_ch1
    assert "Thermodynamics" not in content_ch1

    content_ch2 = ChapterSegmenter.extract_chapter_content(sample_text, ["2"])
    assert "Thermodynamics" in content_ch2
    assert "conservation of energy" in content_ch2.lower()
