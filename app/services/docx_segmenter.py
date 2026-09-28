import io
import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple, Dict, Any
from docx import Document as DocumentFactory
from docx.document import Document as DocumentClass
from docx.text.paragraph import Paragraph
from docx.table import Table
from docx.oxml.ns import qn
from pydantic import BaseModel, Field
from app.core.logger import logger
from app.services.marker_cache import MarkerCache


class TopicMarker(BaseModel):
    id: str = Field(description="Unique identifier for the marker")
    number: Optional[str] = Field(default=None, description="Normalized chapter/section number, e.g. '5', '5.1', 'IV'")
    title: str = Field(description="Cleaned topic or chapter title, e.g. 'Thermodynamics'")
    full_heading: str = Field(description="Full heading text, e.g. 'Chapter-5: Thermodynamics'")
    type: str = Field(default="chapter", description="Marker type: 'chapter', 'section', 'subsection', 'topic'")
    level: int = Field(default=1, description="Hierarchical level: 1 (Chapter/Unit), 2 (Section), 3 (Subsection)")
    start_page: int = Field(default=1, description="Starting page number")
    end_page: Optional[int] = Field(default=None, description="Ending page number")
    body_index: Optional[int] = Field(default=None, description="Zero-based index of the element in the document body")
    start_char: Optional[int] = Field(default=None, description="Character start index if available")
    end_char: Optional[int] = Field(default=None, description="Character end index if available")
    source: str = Field(default="heading_style", description="Discovery source: 'toc', 'heading_style', 'outline_level', 'regex'")
    confidence: float = Field(default=0.5, ge=0, le=1)
    child_topics: List[Dict[str, Any]] = Field(default_factory=list)


from app.core.exceptions import ChapterNotFoundError


class DocxChapterSegmenter:
    """
    Intelligent Chapter and Topic Marker Extractor & Segmenter for Word (.docx) documents.
    Supports DOCX up to 50 MB with full normalization across 'Chapter 5', 'CHAPTER 5', 'Chapter-5',
    'Chapter 5: Title', '5. Title', 'Unit 5', etc.
    Stores normalized number, title, type, start page, and end page.
    Enforces strict extraction without silent arbitrary 30,000-character fallbacks.
    """

    LABEL_REGEX = re.compile(
        r"^(?:chapter|unit|module|lesson|section|part)[\s\-_:]*([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"(?:\s*[:.\-–—]\s*(.*)|\s+(.*)|$)",
        re.IGNORECASE
    )

    DOTTED_REGEX = re.compile(
        r"^([0-9]+(?:\.[0-9]+)+)\.?\s+(.*)$",
        re.IGNORECASE
    )

    SINGLE_NUMBER_DOT_REGEX = re.compile(
        r"^([0-9]+)\.\s+([A-Za-z].*)$",
        re.IGNORECASE
    )

    ROMAN_NUMERAL_REGEX = re.compile(
        r"^([IVXLCDM]+)[\.\:\-–—]\s+(.*)$",
        re.IGNORECASE
    )

    TOC_TITLE_REGEX = re.compile(
        r"^(?:table\s+of\s+contents|contents|index|table\s+des\s+matières)$",
        re.IGNORECASE
    )

    @classmethod
    def load_document(cls, source: Any) -> DocumentClass:
        """Loads a python-docx Document from bytes, BytesIO, or file-like object."""
        if isinstance(source, DocumentClass):
            return source
        if isinstance(source, (bytes, bytearray)):
            return DocumentFactory(io.BytesIO(source))
        if hasattr(source, "read"):
            return DocumentFactory(source)
        raise ValueError("Invalid document source. Expected bytes, file-like object, or Document instance.")

    @classmethod
    def get_body_elements(cls, doc: DocumentClass) -> List[Any]:
        """Returns all paragraphs and tables in their exact document order."""
        elements = []
        for el in doc.element.body:
            if el.tag.endswith("p"):
                elements.append(Paragraph(el, doc))
            elif el.tag.endswith("tbl"):
                elements.append(Table(el, doc))
        return elements

    @classmethod
    def _get_outline_level(cls, p: Paragraph) -> Optional[int]:
        """Extracts native Word OpenXML outline level if configured."""
        try:
            pPr = p._element.find(qn("w:pPr"))
            if pPr is not None:
                lvl_el = pPr.find(qn("w:outlineLvl"))
                if lvl_el is not None:
                    val = lvl_el.get(qn("w:val"))
                    if val is not None and val.isdigit():
                        return int(val) + 1  # 0 -> Level 1 (Heading 1), 1 -> Level 2
        except Exception:
            pass
        return None

    @classmethod
    def _parse_heading_text(cls, text: str) -> Tuple[Optional[str], str, Optional[int], str]:
        """
        Parses heading text to split canonical number, title, level, and marker type.
        Returns: (number_str, title_str, inferred_level, marker_type)
        """
        clean_text = text.strip()

        # 1. Label pattern: "Chapter 5", "CHAPTER 5", "Chapter-5", "Chapter 5: Title"
        m_label = cls.LABEL_REGEX.match(clean_text)
        if m_label:
            num = m_label.group(1).strip()
            rest = (m_label.group(2) or m_label.group(3) or "").strip()
            title = rest if rest else f"Chapter {num}"
            level = 2 if "." in num else 1
            m_type = "section" if level == 2 else "chapter"
            return num, title, level, m_type

        # 2. Dotted decimal: "5.1 Title", "5.1.2 Subtitle"
        m_dotted = cls.DOTTED_REGEX.match(clean_text)
        if m_dotted:
            num = m_dotted.group(1).strip()
            title = m_dotted.group(2).strip()
            dot_count = num.count(".")
            level = 2 if dot_count == 1 else 3
            m_type = "section" if level == 2 else "subsection"
            return num, title, level, m_type

        # 3. Single number dot: "5. Title"
        m_single = cls.SINGLE_NUMBER_DOT_REGEX.match(clean_text)
        if m_single:
            num = m_single.group(1).strip()
            title = m_single.group(2).strip()
            return num, title, 1, "chapter"

        # 4. Roman numeral: "IV. Title", "Chapter IV"
        m_roman = cls.ROMAN_NUMERAL_REGEX.match(clean_text)
        if m_roman:
            num = m_roman.group(1).strip()
            title = m_roman.group(2).strip()
            return num, title, 1, "chapter"

        # Plain text without explicit number
        return None, clean_text, None, "topic"

    @classmethod
    def parse_document_markers(cls, source: Any) -> List[TopicMarker]:
        """
        Scans a Word document and discovers all chapter and topic markers.
        Computes start page and end page for each marker.
        """
        if isinstance(source, (bytes, bytearray)):
            return MarkerCache.get_or_create(
                bytes(source), "docx", lambda: cls._parse_document_markers(source),
                lambda markers: [m.model_dump() for m in markers],
                lambda data: [TopicMarker.model_validate(item) for item in data]
            )
        return cls._parse_document_markers(source)

    @classmethod
    def _parse_document_markers(cls, source: Any) -> List[TopicMarker]:
        doc = cls.load_document(source)
        body_elements = cls.get_body_elements(doc)
        markers: List[TopicMarker] = []

        toc_range = cls._detect_toc_range(body_elements)
        logger.info(f"DOCX scan: {len(body_elements)} body items, TOC range: {toc_range}")

        # Page tracking variables
        current_page = 1
        page_char_accumulator = 0
        PAGE_CHAR_THRESHOLD = 3000

        marker_count = 0
        for idx, item in enumerate(body_elements):
            if not isinstance(item, Paragraph):
                # Count table chars toward page count
                if isinstance(item, Table):
                    page_char_accumulator += sum(len(c.text) for row in item.rows for c in row.cells)
                    if page_char_accumulator >= PAGE_CHAR_THRESHOLD:
                        current_page += page_char_accumulator // PAGE_CHAR_THRESHOLD
                        page_char_accumulator %= PAGE_CHAR_THRESHOLD
                continue

            text = item.text.strip()
            # Check page break
            if "w:br" in item._p.xml and ('w:type="page"' in item._p.xml or "lastRenderedPageBreak" in item._p.xml):
                current_page += 1
                page_char_accumulator = 0
            else:
                page_char_accumulator += len(text) + 2
                if page_char_accumulator >= PAGE_CHAR_THRESHOLD:
                    current_page += page_char_accumulator // PAGE_CHAR_THRESHOLD
                    page_char_accumulator %= PAGE_CHAR_THRESHOLD

            if not text:
                continue

            # Skip paragraphs inside Table of Contents index list itself to avoid duplicate markers
            if toc_range and toc_range[0] <= idx <= toc_range[1]:
                continue

            style_name = (item.style.name or "").strip().lower()
            outline_lvl = cls._get_outline_level(item)
            is_bold = any(run.bold for run in item.runs if run.text.strip())

            num, title, inferred_lvl, m_type = cls._parse_heading_text(text)

            level: Optional[int] = None
            source_tag = "regex"

            # Check 1: Explicit Word Heading Style
            if "heading 1" in style_name or style_name == "title":
                level = 1
                source_tag = "heading_style"
                m_type = "chapter"
            elif "heading 2" in style_name:
                level = 2
                source_tag = "heading_style"
                m_type = "section"
            elif "heading 3" in style_name:
                level = 3
                source_tag = "heading_style"
                m_type = "subsection"
            # Check 2: Word OpenXML outline level
            elif outline_lvl is not None and 1 <= outline_lvl <= 3:
                level = outline_lvl
                source_tag = "outline_level"
                m_type = "chapter" if level == 1 else "section"
            # Check 3: Text matches regex pattern and is reasonably short (<= 150 chars)
            elif inferred_lvl is not None and len(text) <= 150:
                level = inferred_lvl
                source_tag = "regex"
            # Check 4: Standalone short bold line that looks like a title
            elif is_bold and len(text) <= 80 and not text.endswith((".", ",", ";", ":")):
                level = 1
                source_tag = "bold_text"
                m_type = "chapter"

            if level is not None and text:
                marker_count += 1
                marker = TopicMarker(
                    id=f"marker_{marker_count}",
                    level=level,
                    number=num,
                    title=title,
                    full_heading=text,
                    type=m_type,
                    start_page=current_page,
                    body_index=idx,
                    source=source_tag
                    ,confidence=0.9 if source_tag in {"heading_style", "outline_level"} else 0.65
                )
                markers.append(marker)

        # Compute end_page for each marker based on next marker's start_page or estimated document length
        total_estimated_pages = max(current_page, 1)
        for i in range(len(markers)):
            next_m = None
            for j in range(i + 1, len(markers)):
                if markers[j].level <= markers[i].level and markers[j].start_page >= markers[i].start_page:
                    next_m = markers[j]
                    break
            if next_m:
                markers[i].end_page = max(markers[i].start_page, next_m.start_page - 1 if next_m.start_page > markers[i].start_page else markers[i].start_page)
            else:
                markers[i].end_page = total_estimated_pages

        logger.info(f"Discovered {len(markers)} chapter/topic markers across {total_estimated_pages} pages in DOCX.")
        return markers

    @classmethod
    def _detect_toc_range(cls, body_elements: List[Any]) -> Optional[Tuple[int, int]]:
        """Detects starting and ending body index of the Table of Contents if present."""
        toc_start = None
        toc_end = None

        for idx, item in enumerate(body_elements):
            if not isinstance(item, Paragraph):
                continue
            text = item.text.strip()
            style_name = (item.style.name or "").strip().lower()

            if cls.TOC_TITLE_REGEX.match(text) or "toc heading" in style_name:
                toc_start = idx
                continue

            if toc_start is not None:
                if "heading 1" in style_name or cls._get_outline_level(item) == 1:
                    toc_end = idx - 1
                    break
                if idx - toc_start > 50:
                    toc_end = idx
                    break

        if toc_start is not None:
            toc_end = toc_end if toc_end is not None else min(toc_start + 30, len(body_elements) - 1)
            return toc_start, toc_end

        return None

    @classmethod
    def normalize_identifier(cls, text: str) -> str:
        """
        Normalizes chapter query or label:
        'Chapter 5' -> '5'
        'CHAPTER 5' -> '5'
        'Chapter-5' -> '5'
        '5. Title' -> '5'
        '5' -> '5'
        """
        cleaned = text.strip().lower()
        m = re.search(
            r"\b(?:chapter|unit|module|lesson|part|section)[\s\-_:]*([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+)\b",
            cleaned,
            re.IGNORECASE
        )
        if m:
            return m.group(1).lower()
        m2 = re.match(r"^([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+)\b", cleaned, re.IGNORECASE)
        if m2:
            return m2.group(1).lower()
        return cleaned

    @classmethod
    def resolve_target_marker(cls, target: str, markers: List[TopicMarker]) -> Optional[TopicMarker]:
        """
        Resolves user target using normalized chapter number, title, and controlled heuristics.
        Handles variations like 'Chapter 5', 'CHAPTER 5', 'Chapter-5', 'Chapter 5: Title', '5. Title'.
        """
        target_clean = re.sub(r"\bchatper\b", "chapter", target or "", flags=re.I)
        target_clean = re.sub(r"\b(?:ch|chap)\b", "chapter", target_clean, flags=re.I).strip()
        if not target_clean:
            return None

        target_norm = cls.normalize_identifier(target_clean)
        target_lower = target_clean.lower()

        # 1. Exact match on normalized number
        if target_norm:
            for m in markers:
                if m.number and m.number.lower() == target_norm:
                    return m

        # 2. Exact match on title (case-insensitive)
        for m in markers:
            if m.title.lower() == target_lower:
                return m

        # 3. Exact match on full heading
        for m in markers:
            if m.full_heading.lower() == target_lower:
                return m

        # 4. Substring in title or heading
        for m in markers:
            if target_lower in m.title.lower() or target_lower in m.full_heading.lower():
                return m

        # 5. Marker title is substring of target
        for m in markers:
            if len(m.title) >= 3 and m.title.lower() in target_lower:
                return m

        # 6. Word token overlap
        ignore_words = {"chapter", "unit", "module", "lesson", "part", "the", "and", "of", "in", "to", "for"}
        target_tokens = set(re.findall(r"\w+", target_lower)) - ignore_words
        if target_tokens:
            best_marker = None
            best_score = 0
            for m in markers:
                m_tokens = set(re.findall(r"\w+", m.title.lower())) - ignore_words
                overlap = len(target_tokens.intersection(m_tokens))
                if overlap > best_score:
                    best_score = overlap
                    best_marker = m
            if best_score > 0 and best_marker:
                overlap_ratio = best_score / max(1, len(target_tokens))
                title_ratio = SequenceMatcher(None, target_lower, best_marker.title.lower()).ratio()
                if overlap_ratio >= 0.85 or title_ratio >= 0.85:
                    return best_marker

        # Safe fuzzy title match for typos such as "Acid Bses". Never choose
        # a weak or ambiguous match.
        normalized = re.sub(r"[^\w ]", " ", target_lower)
        ranked = sorted(
            ((SequenceMatcher(None, normalized, re.sub(r"[^\w ]", " ", m.title.lower())).ratio(), m) for m in markers),
            key=lambda item: item[0], reverse=True
        )
        if ranked and ranked[0][0] >= 0.85 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.03):
            return ranked[0][1]

        return None

    @classmethod
    def extract_chapter_content(cls, source: Any, chapters: List[str]) -> str:
        """
        Extracts bounded content slices for the requested chapters or topics from a DOCX document.
        NO unsafe 30,000-character fallback. If a requested chapter cannot be found, raises ChapterNotFoundError.
        """
        doc = cls.load_document(source)
        body_elements = cls.get_body_elements(doc)
        markers = cls.parse_document_markers(doc)

        if not markers:
            logger.warning("No structured markers detected in DOCX.")
            if chapters:
                raise ChapterNotFoundError(chapters[0], [])
            # If no chapters requested and no markers, extract all text
            return cls._extract_raw_body_text(body_elements)

        if not chapters:
            logger.info("No target chapters specified. Returning all body content.")
            return cls._extract_raw_body_text(body_elements)

        combined_slices = []

        for target in chapters:
            target_str = target.strip()
            if not target_str:
                continue

            matched = cls.resolve_target_marker(target_str, markers)
            if not matched:
                logger.error(f"Target chapter/topic '{target_str}' could not be matched in DOCX markers.")
                raise ChapterNotFoundError(target_str, markers)

            start_idx = matched.body_index

            # Find next marker of equal or higher hierarchy (level <= matched.level)
            end_idx = len(body_elements)
            next_marker = None
            for subsequent in markers:
                if subsequent.body_index > start_idx and subsequent.level <= matched.level:
                    end_idx = subsequent.body_index
                    next_marker = subsequent
                    break

            # Extract actual educational body text beneath the heading marker
            content_start_idx = start_idx + 1 if start_idx + 1 < end_idx else start_idx
            slice_text = cls._extract_elements_slice(body_elements, content_start_idx, end_idx).strip()

            start_p = matched.start_page
            end_p = matched.end_page or (next_marker.start_page - 1 if next_marker and next_marker.start_page > start_p else start_p)
            total_pages_extracted = max(1, end_p - start_p + 1)
            if next_marker:
                next_info = f"next chapter {next_marker.number or next_marker.title} starts page {next_marker.start_page}"
            else:
                next_info = "no next chapter marker"

            logger.info(
                f"[DocxChapterSegmenter] Selected chapter {target_str}, start page {start_p}, {next_info}, "
                f"extracting pages {start_p}–{end_p}, total pages extracted {total_pages_extracted}, "
                f"extracted {len(slice_text)} characters"
            )

            if slice_text:
                combined_slices.append(slice_text)

        result = "\n\n".join(combined_slices).strip()
        if not result:
            raise ChapterNotFoundError(chapters[0] if chapters else "unknown", markers)

        return result

    @classmethod
    def _extract_elements_slice(cls, body_elements: List[Any], start_idx: int, end_idx: int) -> str:
        """Extracts text and markdown-formatted tables for a range of body elements."""
        output = []
        for item in body_elements[start_idx:end_idx]:
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    output.append(text)
            elif isinstance(item, Table):
                table_lines = []
                for row in item.rows:
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(row_cells):
                        table_lines.append("| " + " | ".join(row_cells) + " |")
                if table_lines:
                    table_str = "\n" + "\n".join(table_lines) + "\n"
                    output.append(table_str)

        return "\n\n".join(output)

    @classmethod
    def _extract_raw_body_text(cls, body_elements: List[Any]) -> str:
        """Extracts all text from paragraphs and tables."""
        output = []
        for item in body_elements:
            if isinstance(item, Paragraph):
                t = item.text.strip()
                if t:
                    output.append(t)
            elif isinstance(item, Table):
                for row in item.rows:
                    row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                    if row_text:
                        output.append(row_text)
        return "\n\n".join(output)
