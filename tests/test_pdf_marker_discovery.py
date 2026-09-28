import pymupdf

from app.core.exceptions import ChapterNotFoundError
from app.services.chapter_segmenter import ChapterSegmenter
from app.services.docx_segmenter import TopicMarker


def make_pdf(with_outline=False, with_contents=False, outlier=False):
    doc = pymupdf.open()
    chapter_pages = [(3, "Acids and Bases"), (7, "Electric Circuits")]
    if outlier:
        chapter_pages.append((10, "Unrelated Appendix"))
    for page_no in range(1, 13):
        page = doc.new_page()
        if with_contents and page_no == 1:
            page.insert_text((60, 60), "Contents", fontsize=18)
            page.insert_text((60, 100), "1 Acids and Bases ........ 3\n2 Electric Circuits ....... 7", fontsize=10)
        elif any(start == page_no for start, _ in chapter_pages):
            title = next(title for start, title in chapter_pages if start == page_no)
            page.insert_text((60, 90), title, fontsize=24, fontname="hebo")
            page.insert_text((60, 140), "Definitions, principles, examples, and detailed educational explanations.", fontsize=10)
        else:
            page.insert_text((60, 90), "8: Why do acids not show metallic properties?", fontsize=10)
            page.insert_text((60, 120), "Body text explains the subject in detail.", fontsize=10)
    if with_outline:
        toc = [[1, "Chapter 1: Acids and Bases", 3], [1, "Chapter 2: Electric Circuits", 7]]
        if outlier:
            toc.append([1, "Chapter 9: Unrelated Appendix", 10])
        doc.set_toc(toc)
    return doc.write()


def test_contents_and_font_detection_return_real_chapters_and_ranges():
    markers = ChapterSegmenter.parse_pdf_markers(make_pdf(with_contents=True))
    assert [(m.number, m.start_page, m.end_page) for m in markers] == [("1", 3, 6), ("2", 7, 12)]
    assert all("Why do acids" not in marker.title for marker in markers)


def test_sequence_filter_drops_numbered_outlier():
    markers = ChapterSegmenter.parse_pdf_markers(make_pdf(with_outline=True, outlier=True))
    assert [marker.number for marker in markers] == ["1", "2"]


def test_forgiving_target_variants_and_closest_candidates():
    markers = ChapterSegmenter.parse_pdf_markers(make_pdf(with_outline=True))
    for query in ("Chatper 2", "ch-2", "2", "Chapter 2", "Electric Circuits"):
        assert ChapterSegmenter.resolve_marker(query, markers).number == "2"

    assert ChapterSegmenter.resolve_marker("Thermodynamics", markers) is None
    closest = ChapterSegmenter.closest_markers("Thermodynamics", markers)
    assert len(closest) == 2
    try:
        ChapterSegmenter.extract_pdf_chapter_content(make_pdf(with_outline=True), ["Thermodynamics"])
    except ChapterNotFoundError as error:
        assert "pages" in str(error)
    else:
        raise AssertionError("missing chapter should fail explicitly")


def test_marker_cache_is_written_and_reused(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    data = make_pdf(with_outline=True)
    first = ChapterSegmenter.parse_pdf_markers(data)
    cache_files = list((tmp_path / "marker_cache").glob("*.json"))
    second = ChapterSegmenter.parse_pdf_markers(data)
    assert cache_files
    assert [(m.number, m.start_page) for m in first] == [(m.number, m.start_page) for m in second]


def test_wrapped_heading_merges_before_fragment_filtering():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 90), "Acids, Bases", fontsize=24, fontname="hebo")
    page.insert_text((60, 116), "and Salts", fontsize=24, fontname="hebo")
    page.insert_text((60, 160), "This chapter contains detailed educational explanations and examples.", fontsize=10)
    markers = ChapterSegmenter.parse_pdf_markers(doc.write())
    assert any(marker.title == "Acids, Bases and Salts" for marker in markers)
    assert not any(marker.title in {"Acids, Bases", "and Salts"} for marker in markers)


def test_numbered_depth_is_child_topic():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 90), "Chapter 4: Matter", fontsize=24, fontname="hebo")
    page.insert_text((60, 140), "4.2.2 States of Matter", fontsize=18, fontname="hebo")
    page.insert_text((60, 190), "Matter exists in different states with distinct properties.", fontsize=10)
    markers = ChapterSegmenter.parse_pdf_markers(doc.write())
    assert [marker.number for marker in markers] == ["4"]
    assert markers[0].child_topics[0]["number"] == "4.2.2"


def test_matching_normalizes_commas_and_joins_adjacent_fragments():
    markers = [
        TopicMarker(id="a", title="Title Words", full_heading="Title Words", start_page=4, end_page=8, number=None),
        TopicMarker(id="b", title="And More", full_heading="And More", start_page=4, end_page=8, number=None),
    ]
    match = ChapterSegmenter.resolve_marker("Title Words And More", markers)
    assert match is not None
    assert match.title == "Title Words And More"

    comma_marker = TopicMarker(id="c", title="Acids, Bases and Salts", full_heading="Acids, Bases and Salts", start_page=1, number="1")
    assert ChapterSegmenter.resolve_marker("Acids Bases and Salts", [comma_marker]) is comma_marker
