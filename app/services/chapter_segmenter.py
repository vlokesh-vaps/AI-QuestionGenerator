import bisect
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Tuple, Optional, Dict, Any
from app.core.logger import logger
from app.services.docx_segmenter import TopicMarker
from app.services.marker_cache import MarkerCache
from app.core.exceptions import ChapterNotFoundError, InsufficientSourceContentError

try:
    from rapidfuzz.fuzz import ratio as fuzzy_ratio
except ImportError:  # Keep local development usable before dependency installation.
    fuzzy_ratio = lambda left, right: SequenceMatcher(None, left, right).ratio() * 100


class ChapterSegmenter:
    """
    Ported and enhanced Chapter/Section Marker Parser for raw text and PDF text extractions.
    Matches variations: 'Chapter 5', 'CHAPTER 5', 'Chapter-5', 'Chapter 5: Title', '5. Title', 'Unit 5'.
    Stores normalized number, title, type, start page, and end page.
    Enforces complete multi-page chapter extraction without treating the marker page alone as the complete content.
    """

    CHAPTER_REGEX = re.compile(
        r"(?:^|\n)\s*(?:"
        r"(?:chapter|unit|lesson|module|section|part)[\s\-_:]+([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*[:.\-–—]\s*(.*?))?"
        r"|"
        r"([0-9]+(?:\.[0-9]+)*)\.\s+([A-Za-z].*?)"
        r"|"
        r"([IVXLCDM]+)[\.\:\-–—]\s+([A-Za-z].*?)"
        r")(?=\n|$)",
        re.IGNORECASE
    )

    EXERCISE_KEYWORDS = {
        "exercise", "exercises", "question", "questions", "assignment", "assignments",
        "summary", "activity", "activities", "review", "revision", "practice", "test"
    }

    @classmethod
    def _clean_query(cls, value: str) -> str:
        value = unicodedata.normalize("NFKC", value or "").lower().strip()
        value = re.sub(r"\bchatper\b", "chapter", value)
        value = re.sub(r"\bchap\b|\bch\b", "chapter", value)
        value = re.sub(r"\b(?:chapter|unit|lesson|module|topic)\b", " ", value)
        value = re.sub(r"[^\w.]+", " ", value).strip()
        if not re.fullmatch(r"\d+(?:\.\d+)*", value):
            value = re.sub(r"^\d+(?:\.\d+)*\s*", "", value)
        return value.strip()

    @classmethod
    def _looks_like_exercise(cls, text: str, context: str = "") -> bool:
        value = text.strip()
        if not value or len(value) > 90 or value.endswith(("?", ".", ",", ";")):
            return True
        if re.match(r"(?i)^(why|what|how|when|where|who|which|define|explain|calculate|compare|write|state)\b", value):
            return True
        words = re.findall(r"[A-Za-z]+", value)
        if len(words) >= 5 and sum(w.islower() for w in words) >= len(words) * 0.65:
            return True
        return any(re.search(rf"\b{re.escape(word)}\b", context, re.I) for word in cls.EXERCISE_KEYWORDS)

    @classmethod
    def _number_sort_key(cls, value: Optional[str]) -> Tuple[int, ...]:
        if not value:
            return (10**9,)
        try:
            return tuple(int(part) for part in re.findall(r"\d+", value))
        except ValueError:
            return (10**9,)

    @classmethod
    def _filter_pdf_markers(cls, markers: List[TopicMarker], total_pages: int) -> List[TopicMarker]:
        chapters = [m for m in markers if m.level == 1 and m.type == "chapter"]
        by_number: Dict[str, TopicMarker] = {}
        for marker in chapters:
            if marker.number and marker.number.isdigit():
                key = marker.number.lower()
                if key not in by_number or marker.confidence > by_number[key].confidence:
                    by_number[key] = marker
        numbered = sorted(by_number.values(), key=lambda m: (m.start_page, cls._number_sort_key(m.number)))
        if numbered:
            best_run: List[TopicMarker] = []
            for candidate in numbered:
                run = [candidate]
                expected = int(candidate.number) + 1
                for following in numbered[numbered.index(candidate) + 1:]:
                    if int(following.number) == expected:
                        run.append(following)
                        expected += 1
                if len(run) > len(best_run):
                    best_run = run
            keep = {id(m) for m in best_run}
            # Preserve explicitly titled non-numbered chapters only when they are not exercise-like.
            chapters = [m for m in chapters if id(m) in keep or (not m.number and not cls._looks_like_exercise(m.title))]
        chapters = [m for m in chapters if not cls._looks_like_exercise(m.title)]
        for marker in markers:
            if marker.level > 1:
                parents = [c for c in chapters if c.start_page <= marker.start_page]
                parent = max(parents, key=lambda c: c.start_page) if parents else None
                if parent and not cls._looks_like_exercise(marker.title):
                    parent.child_topics.append(marker.model_dump(exclude={"child_topics"}))
        result = chapters
        result.sort(key=lambda m: (m.start_page, cls._number_sort_key(m.number)))
        for index, marker in enumerate(result):
            next_chapter = result[index + 1] if index + 1 < len(result) else None
            marker.end_page = max(marker.start_page, (next_chapter.start_page - 1) if next_chapter else total_pages)
        return result

    @staticmethod
    def normalize_identifier(text: str) -> str:
        """Extracts canonical chapter identifier: 'Chapter-5' -> '5', 'CHAPTER 5' -> '5', 'IV' -> 'iv'."""
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
    def resolve_marker(cls, target: str, markers: List[TopicMarker]) -> Optional[TopicMarker]:
        return cls.resolve_marker_forgiving(target, markers)

    @classmethod
    def resolve_marker_forgiving(cls, target: str, markers: List[TopicMarker]) -> Optional[TopicMarker]:
        """Resolve numbers, common misspellings, prefixes, and fuzzy titles safely."""
        cls._merge_adjacent_marker_fragments(target, markers)
        query = cls._clean_query(target)
        if not query:
            return None
        number_match = re.search(r"\b(\d+(?:\.\d+)*)\b", query)
        if number_match:
            number = number_match.group(1)
            number_matches = [m for m in markers if m.number and m.number.lower() == number.lower()]
            if len(number_matches) == 1:
                return number_matches[0]
            if number_matches:
                query_without_number = re.sub(rf"\b{re.escape(number)}\b", "", query).strip()
                if query_without_number:
                    ranked = sorted(number_matches, key=lambda m: fuzzy_ratio(query_without_number, cls._clean_query(m.title)), reverse=True)
                    if ranked and fuzzy_ratio(query_without_number, cls._clean_query(ranked[0].title)) >= 85:
                        return ranked[0]
                return None

        ranked = sorted(
            ((fuzzy_ratio(query, cls._clean_query(m.title)), m) for m in markers),
            key=lambda item: item[0], reverse=True
        )
        if ranked and ranked[0][0] >= 85 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 3):
            return ranked[0][1]
        return None

    @classmethod
    def _merge_adjacent_marker_fragments(cls, target: str, markers: List[TopicMarker]) -> None:
        """Safety net for PDFs that expose one wrapped heading as two markers."""
        query = cls._clean_query(target)
        index = 0
        while index + 1 < len(markers):
            left, right = markers[index], markers[index + 1]
            if left.start_page != right.start_page or left.level != 1 or right.level != 1:
                index += 1
                continue
            combined = cls._clean_query(f"{left.title} {right.title}")
            if combined == query or fuzzy_ratio(combined, query) >= 85:
                left.title = f"{left.title.rstrip(' ,;:-')} {right.title.lstrip()}".strip()
                left.full_heading = left.title
                left.end_page = max(left.end_page or left.start_page, right.end_page or right.start_page)
                left.confidence = max(left.confidence, right.confidence)
                del markers[index + 1]
                continue
            index += 1

    @classmethod
    def closest_markers(cls, target: str, markers: List[TopicMarker], limit: int = 5) -> List[TopicMarker]:
        query = cls._clean_query(target)
        return [m for _, m in sorted(
            ((fuzzy_ratio(query, cls._clean_query(m.title)), m) for m in markers),
            key=lambda item: item[0], reverse=True
        )[:limit]]

    @classmethod
    def _legacy_resolve_marker(cls, target: str, markers: List[TopicMarker]) -> Optional[TopicMarker]:
        target_clean = target.strip()
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

        # 6. Token overlap
        ignore_words = {"chapter", "unit", "section", "module", "the", "and", "of", "in", "to", "for"}
        words = set(re.findall(r"\w+", target_lower)) - ignore_words
        if words:
            best = None
            best_score = 0
            for m in markers:
                m_words = set(re.findall(r"\w+", m.title.lower())) - ignore_words
                overlap = len(words.intersection(m_words))
                if overlap > best_score:
                    best_score = overlap
                    best = m
            if best_score > 0 and best:
                return best

        return None

    @classmethod
    def parse_text_markers(cls, full_text: str, page_offsets: List[int] = None) -> List[TopicMarker]:
        """
        Parses all chapter/section markers from full text, computing page mapping if offsets are provided.
        """
        markers: List[TopicMarker] = []
        matches = list(cls.CHAPTER_REGEX.finditer(full_text))

        for idx, m in enumerate(matches):
            raw_match = m.group(0).strip()
            num = None
            title = ""

            if m.group(1):
                num = m.group(1).strip()
                title = (m.group(2) or "").strip()
            elif m.group(3):
                num = m.group(3).strip()
                title = (m.group(4) or "").strip()
            elif m.group(5):
                num = m.group(5).strip()
                title = (m.group(6) or "").strip()

            if not title:
                title = f"Chapter {num}" if num else raw_match

            # Type and level
            level = 1
            marker_type = "chapter"
            if num and "." in num:
                level = 2 if num.count(".") == 1 else 3
                marker_type = "section" if level == 2 else "subsection"

            start_char = m.start()

            # Estimate page numbers based on page offsets or ~3000 chars per page
            if page_offsets:
                p_idx = bisect.bisect_right(page_offsets, start_char) - 1
                start_page = max(1, p_idx + 1)
            else:
                start_page = max(1, start_char // 3000 + 1)

            marker = TopicMarker(
                id=f"marker_{idx + 1}",
                number=num,
                title=title,
                full_heading=raw_match,
                type=marker_type,
                level=level,
                start_page=start_page,
                end_page=None,
                start_char=start_char,
                end_char=None,
                source="regex"
            )
            markers.append(marker)

        # Compute end_char and end_page for each marker based on next marker of equal or higher hierarchy
        total_pages = len(page_offsets) if page_offsets else max(1, len(full_text) // 3000 + 1)
        for i, m in enumerate(markers):
            next_marker = None
            for j in range(i + 1, len(markers)):
                if markers[j].level <= m.level:
                    next_marker = markers[j]
                    break
            if next_marker:
                m.end_char = next_marker.start_char
                if page_offsets and next_marker.start_char is not None:
                    next_p = bisect.bisect_right(page_offsets, next_marker.start_char) - 1
                    next_page = max(1, next_p + 1)
                    m.end_page = max(m.start_page, next_page - 1 if next_page > m.start_page else m.start_page)
                else:
                    m.end_page = max(m.start_page, next_marker.start_page - 1 if next_marker.start_page > m.start_page else m.start_page)
            else:
                m.end_char = len(full_text)
                m.end_page = total_pages

        return markers

    @classmethod
    def parse_pdf_markers(cls, pdf_bytes: bytes) -> List[TopicMarker]:
        """
        Extracts chapter/topic markers from PDF bookmarks (TOC) or page-by-page scanning.
        Computes accurate start_page and end_page bounds based on the next chapter marker.
        """
        return cls._parse_pdf_markers_v2(pdf_bytes)

        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        total_pages = max(1, doc.page_count)
        toc = doc.get_toc()
        markers: List[TopicMarker] = []

        if toc:
            for idx, item in enumerate(toc):
                lvl, title, page = item[0], item[1].strip(), item[2]
                if not title:
                    continue
                num_match = re.search(
                    r"\b(?:chapter|unit|section|part|module)?\s*([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+)\b",
                    title,
                    re.IGNORECASE
                )
                num = num_match.group(1) if num_match else None
                m_type = "chapter" if lvl == 1 else ("section" if lvl == 2 else "subsection")
                markers.append(
                    TopicMarker(
                        id=f"pdf_toc_{idx + 1}",
                        number=num,
                        title=title,
                        full_heading=title,
                        type=m_type,
                        level=min(lvl, 3),
                        start_page=max(1, min(page, total_pages)),
                        end_page=None,
                        source="pdf_toc"
                    )
                )

        if not markers:
            # Page-by-page scanning
            for page_idx in range(doc.page_count):
                page_num = page_idx + 1
                text = doc[page_idx].get_text("text")
                if not text.strip():
                    continue

                # Check if this page is a printed Table of Contents
                is_toc_page = bool(re.search(r"^\s*(?:table\s+of\s+contents|contents|index)\b", text, re.IGNORECASE | re.MULTILINE))
                if is_toc_page:
                    for line in text.split("\n"):
                        line_str = line.strip()
                        toc_m = re.match(
                            r"^(?:chapter|unit|section|part|module)?\s*([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+)[:.\s\-–—]*(.*?)(?:[\.\s\-–—]{2,}|\t|\s{2,})([0-9]+)$",
                            line_str,
                            re.IGNORECASE
                        )
                        if toc_m:
                            c_num = toc_m.group(1)
                            c_title = toc_m.group(2).strip() or f"Chapter {c_num}"
                            target_p = int(toc_m.group(3))
                            if 1 <= target_p <= total_pages:
                                lvl = 2 if "." in c_num else 1
                                markers.append(
                                    TopicMarker(
                                        id=f"pdf_text_toc_{len(markers) + 1}",
                                        number=c_num,
                                        title=c_title,
                                        full_heading=line_str,
                                        type="chapter" if lvl == 1 else "section",
                                        level=lvl,
                                        start_page=target_p,
                                        end_page=None,
                                        source="text_toc"
                                    )
                                )
                    continue

                # On body pages, scan headings in top lines
                lines = [l.strip() for l in text.split("\n") if l.strip()][:10]
                for line in lines:
                    m = cls.CHAPTER_REGEX.search(line)
                    if m:
                        c_num = m.group(1) or m.group(3) or m.group(5)
                        c_title = (m.group(2) or m.group(4) or m.group(6) or "").strip()
                        if not c_title:
                            c_title = f"Chapter {c_num}" if c_num else line
                        lvl = 1
                        if c_num and "." in c_num:
                            lvl = 2 if c_num.count(".") == 1 else 3
                        # Avoid duplicate marker for same number and page
                        if not any(existing.number == c_num and existing.start_page == page_num for existing in markers):
                            markers.append(
                                TopicMarker(
                                    id=f"pdf_page_h_{len(markers) + 1}",
                                    number=c_num,
                                    title=c_title,
                                    full_heading=line,
                                    type="chapter" if lvl == 1 else "section",
                                    level=lvl,
                                    start_page=page_num,
                                    end_page=None,
                                    source="page_heading"
                                )
                            )
                        break

        # Deduplicate markers, keeping distinct chapter number/title and start page
        unique_markers: List[TopicMarker] = []
        seen_keys = set()
        for m in markers:
            key = (m.number.lower() if m.number else m.title.lower(), m.start_page)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_markers.append(m)

        # Sort markers strictly by start_page and hierarchical level
        unique_markers.sort(key=lambda m: (m.start_page, m.level))

        # Compute end_page for each marker based on next marker of equal or higher hierarchy
        for i, m in enumerate(unique_markers):
            next_marker = None
            for j in range(i + 1, len(unique_markers)):
                if unique_markers[j].level <= m.level and unique_markers[j].start_page > m.start_page:
                    next_marker = unique_markers[j]
                    break
            if next_marker:
                m.end_page = max(m.start_page, next_marker.start_page - 1)
            else:
                m.end_page = total_pages

        return unique_markers

    @classmethod
    def _parse_pdf_markers_v2(cls, pdf_bytes: bytes) -> List[TopicMarker]:
        """Multi-signal PDF discovery: outline, verified contents, fonts, then regex."""
        import pymupdf
        return MarkerCache.get_or_create(
            pdf_bytes, "pdf_v6", lambda: cls._scan_pdf_markers(pdf_bytes),
            lambda markers: [m.model_dump() for m in markers],
            lambda data: [TopicMarker.model_validate(item) for item in data]
        )

    @classmethod
    def _scan_pdf_markers(cls, pdf_bytes: bytes) -> List[TopicMarker]:
        import pymupdf
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        total_pages = max(1, doc.page_count)
        candidates: List[TopicMarker] = []

        # 1. Embedded outline/bookmarks.
        for idx, item in enumerate(doc.get_toc()):
            level, title, page = int(item[0]), str(item[1]).strip(), int(item[2] or 1)
            if not title or level > 3:
                continue
            match = re.search(r"(?i)\b(?:chapter|unit|lesson|module|part|section)?\s*([0-9]+(?:\.[0-9]+)*|[ivxlcdm]+)\b", title)
            number = match.group(1) if match else None
            level = min(level, 3)
            candidates.append(TopicMarker(
                id=f"outline_{idx + 1}", number=number, title=title, full_heading=title,
                type="chapter" if level == 1 else "section", level=level,
                start_page=max(1, min(page, total_pages)), source="pdf_outline", confidence=0.98
            ))

        # 2. Contents rows. Printed page numbers are accepted only after title verification.
        contents_pages = []
        page_texts = []
        for page_idx in range(total_pages):
            text = doc[page_idx].get_text("text")
            page_texts.append(text)
            if re.search(r"(?im)^\s*(?:table\s+of\s+contents|contents|index)\s*$", text):
                contents_pages.append(page_idx)
        for page_idx in contents_pages:
            for line in page_texts[page_idx].splitlines():
                line = re.sub(r"\s+", " ", line).strip()
                match = re.match(r"^(?:chapter|unit|lesson|module|part)?\s*([0-9]+(?:\.[0-9]+)*)\s*[:.\-–—]?\s*(.+?)\s*(?:\.{2,}|\s{2,}|\t+)\s*(\d+)$", line, re.I)
                if not match:
                    continue
                number, title, printed_page = match.group(1), match.group(2).strip(" .-"), int(match.group(3))
                if "." in number or cls._looks_like_exercise(title):
                    continue
                physical_page = cls._verify_printed_page(doc, printed_page, title)
                if physical_page:
                    candidates.append(TopicMarker(
                        id=f"contents_{len(candidates) + 1}", number=number, title=title,
                        full_heading=line, type="chapter", level=1, start_page=physical_page,
                        source="pdf_contents", confidence=0.995
                    ))

        # 3. Font-based headings near the top of pages.
        sizes = []
        page_lines = []
        for page_idx in range(total_pages):
            lines = []
            for block in doc[page_idx].get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    text = re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip()
                    size = max(float(s.get("size", 0)) for s in spans)
                    bold = any("bold" in str(s.get("font", "")).lower() or int(s.get("flags", 0)) & 16 for s in spans)
                    top = min(float(s.get("bbox", [0, 0, 0, 0])[1]) for s in spans)
                    sizes.extend([size] * max(1, len(text)))
                    bbox = spans[0].get("bbox", [0, 0, 0, 0])
                    left = min(float(s.get("bbox", [0, 0, 0, 0])[0]) for s in spans)
                    height = max(1.0, float(bbox[3]) - float(bbox[1]))
                    lines.append({"text": text, "size": size, "bold": bold, "top": top, "left": left, "height": height})
            page_lines.append(lines)
        dominant = sorted(sizes)[len(sizes) // 2] if sizes else 10
        for page_idx, lines in enumerate(page_lines):
            for line in cls._merge_heading_lines(lines):
                text, size, bold, top = line["text"], line["size"], line["bold"], line["top"]
                if len(text) > 90 or top > 300 or cls._looks_like_exercise(text):
                    continue
                if text.strip().lower() in {"contents", "table of contents", "index"}:
                    continue
                match = re.match(r"(?i)^\s*(?:chapter|unit|lesson|module|part)\s+([0-9]+|[ivxlcdm]+)\b\s*[:.\-–—]?\s*(.*)$", text)
                number, title, level, marker_type = cls._classify_heading(text)
                if size >= dominant + 3 or (bold and size >= dominant + 1.5):
                    candidates.append(TopicMarker(
                        id=f"font_{len(candidates) + 1}", number=number, title=title,
                        full_heading=text, type=marker_type, level=level, start_page=page_idx + 1,
                        source="pdf_font", confidence=0.84 if number else 0.72
                    ))

        # 4. Explicit standalone chapter/unit fallback.
        for page_idx, text in enumerate(page_texts):
            for line in text.splitlines()[:15]:
                line = re.sub(r"\s+", " ", line).strip()
                match = re.match(r"(?i)^(?:chapter|unit|lesson|module|part)\s*[-:]?\s*([0-9]+|[ivxlcdm]+)\s*[:.\-–—]?\s*(.{0,80})$", line)
                if match and not cls._looks_like_exercise(line):
                    candidates.append(TopicMarker(
                        id=f"regex_{len(candidates) + 1}", number=match.group(1),
                        title=match.group(2).strip() or f"Chapter {match.group(1)}", full_heading=line,
                        type="chapter", level=1, start_page=page_idx + 1,
                        source="pdf_regex", confidence=0.65
                    ))

        merged: Dict[Tuple[Optional[str], int], TopicMarker] = {}
        for marker in candidates:
            key = cls._clean_query(marker.title.split(":", 1)[-1]) or (marker.number or "").lower()
            if key not in merged or marker.confidence > merged[key].confidence:
                merged[key] = marker
        return cls._filter_pdf_markers(list(merged.values()), total_pages)

    @classmethod
    def _merge_heading_lines(cls, lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge wrapped heading lines before title/exercise filtering."""
        merged: List[Dict[str, Any]] = []
        for line in lines[:24]:
            if not merged:
                merged.append(dict(line))
                continue
            previous = merged[-1]
            # PDF text bboxes often overlap vertically even when the lines are
            # consecutive; compare line-top distance rather than bbox gap.
            gap = line["top"] - previous["top"]
            same_style = round(line["size"]) == round(previous["size"]) and line["bold"] == previous["bold"]
            aligned = abs(line["left"] - previous["left"]) <= max(18.0, previous["height"] * 1.5)
            label_join = bool(re.match(r"(?i)^\s*(?:chapter|unit|lesson|module|part)?\s*\d+(?:\.\d+)*\s*[:.)-]?\s*$", previous["text"]))
            if 0 < gap < max(previous["height"], line["height"]) * (1.5 if same_style else 2.0) and aligned and (same_style or label_join):
                joined = previous["text"].rstrip() + " " + line["text"].lstrip()
                previous["text"] = re.sub(r"\s+", " ", re.sub(r"(?<=\w)-\s+(?=\w)", "", joined)).strip()
                previous["height"] = (line["top"] + line["height"]) - previous["top"]
            else:
                merged.append(dict(line))
        return merged

    @staticmethod
    def _classify_heading(text: str) -> Tuple[Optional[str], str, int, str]:
        explicit = re.match(r"(?i)^\s*(?:chapter|unit|lesson|module|part)\s*[-:]?\s*([0-9]+(?:\.\d+)*|[ivxlcdm]+)\s*[:.)-]?\s*(.*)$", text)
        numbered = explicit or re.match(r"^\s*(\d+(?:\.\d+)*)\s*[:.)-]?\s+(.+)$", text)
        if not numbered:
            return None, text.strip(), 1, "chapter"
        number = numbered.group(1)
        title = numbered.group(2).strip() or f"Chapter {number}"
        level = 1 if "." not in number else min(3, number.count(".") + 1)
        marker_type = "chapter" if level == 1 else ("section" if level == 2 else "subsection")
        return number, title, level, marker_type

    @staticmethod
    def _verify_printed_page(doc: Any, printed_page: int, title: str) -> Optional[int]:
        if printed_page < 1:
            return None
        words = [word.lower() for word in re.findall(r"[A-Za-z]{4,}", title)[:5]]
        for offset in range(-15, 16):
            physical = printed_page + offset
            if not 1 <= physical <= doc.page_count:
                continue
            page_text = doc[physical - 1].get_text("text")
            if re.search(r"(?im)^\s*(?:table\s+of\s+contents|contents|index)\s*$", page_text):
                continue
            text = "\n".join(page_text.splitlines()[:10]).lower()
            matched_words = sum(word in text for word in words)
            if words and (matched_words == len(words) or (len(words) == 1 and matched_words == 1)):
                return physical
        return None

    @classmethod
    def extract_pdf_chapter_content(cls, pdf_bytes: bytes, chapters: List[str], page_start: Optional[int] = None, page_end: Optional[int] = None) -> str:
        """
        Extracts complete multi-page chapter content from a PDF document.
        Calculates range from current chapter start page through the page immediately before
        the next chapter start page (e.g. pages 12–34 for Chapter 2 if Chapter 3 starts on page 35).
        Extracts all paragraphs, headings, tables, lists and substantive text belonging to that range.
        Removes repeated headers, footers, page numbers, and structural noise.
        """
        import pymupdf

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        total_pages = doc.page_count

        if not chapters:
            first = max(1, page_start or 1)
            last = min(total_pages, page_end or total_pages)
            all_pages_text = [doc[i].get_text("text") for i in range(first - 1, last)]
            return "\n\n".join(all_pages_text).strip()

        markers = cls.parse_pdf_markers(pdf_bytes)
        if not markers:
            logger.error("No chapter or topic markers could be discovered in the PDF.")
            if page_start is not None or page_end is not None:
                first = max(1, page_start or 1)
                last = min(total_pages, page_end or total_pages)
                selected_text = "\n\n".join(doc[i].get_text("text") for i in range(first - 1, last)).strip()
                if not selected_text:
                    raise ValueError("Scanned PDF detected: the selected pages contain no extractable text. OCR is required.")
                return selected_text
            raise ChapterNotFoundError(chapters[0] if chapters else "unknown", [])

        combined_content = []
        for ch in chapters:
            target = ch.strip()
            if not target:
                continue
            matched = cls.resolve_marker(target, markers)
            if not matched:
                logger.error(f"Chapter '{target}' could not be matched in PDF markers.")
                raise ChapterNotFoundError(target, cls.closest_markers(target, markers))

            start_p = max(1, min(matched.start_page, total_pages))

            # Find the next chapter marker of equal or higher hierarchy with start_page > start_p
            next_marker = None
            for m in markers:
                if m.start_page > start_p and m.level <= matched.level:
                    if next_marker is None or m.start_page < next_marker.start_page:
                        next_marker = m

            if next_marker:
                next_ch_name = next_marker.number or next_marker.title
                next_ch_start = next_marker.start_page
                end_p = max(start_p, next_ch_start - 1)
                next_info = f"next chapter {next_ch_name} starts page {next_ch_start}"
            else:
                end_p = total_pages
                next_info = "no next chapter marker"

            if page_start is not None:
                start_p = max(start_p, page_start)
            if page_end is not None:
                end_p = min(end_p, page_end)
            end_p = min(end_p, total_pages)
            if end_p < start_p:
                raise ValueError(f"Requested page range {page_start}-{page_end} does not overlap the selected chapter.")
            total_pages_extracted = max(1, end_p - start_p + 1)

            # Extract all pages in range [start_p, end_p] (1-based inclusive)
            # PyMuPDF zero-based page index range: range(start_p - 1, end_p)
            extracted_pages_text = []
            raw_extractable_chars = 0
            for page_idx in range(start_p - 1, end_p):
                raw_text = doc[page_idx].get_text("text")
                raw_extractable_chars += len(raw_text.strip())
                cleaned_page_lines = []
                lines = raw_text.split("\n")
                for line_idx, line in enumerate(lines):
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    # Remove standalone page numbers (e.g. '12', 'Page 12 of 100', '- 12 -')
                    if re.match(r"^(?:page\s*)?[0-9ivxlcdm]+(?:\s+of\s+[0-9]+)?$", line_stripped, re.IGNORECASE):
                        continue
                    if re.match(r"^[-–—]\s*[0-9ivxlcdm]+\s*[-–—]$", line_stripped):
                        continue
                    # On the very first page of the chapter, strip the chapter heading itself if at the top
                    if page_idx == start_p - 1 and line_idx < 3:
                        if matched.full_heading.lower() in line_stripped.lower() or (matched.title and matched.title.lower() in line_stripped.lower()):
                            continue
                    cleaned_page_lines.append(line)
                page_content = "\n".join(cleaned_page_lines).strip()
                if page_content:
                    extracted_pages_text.append(page_content)

            chapter_text = "\n\n".join(extracted_pages_text).strip()

            # Detailed log format matching the exact user specification
            logger.info(
                f"Selected chapter {target}, start page {start_p}, {next_info}, "
                f"extracting pages {start_p}–{end_p}, total pages extracted {total_pages_extracted}, "
                f"extracted {len(chapter_text)} characters"
            )

            # Content sufficiency validation floor on the extracted chapter text
            substantive_words = len(re.findall(r"\b[A-Za-z0-9_-]{2,}\b", chapter_text))
            if not chapter_text.strip() and raw_extractable_chars == 0:
                raise ValueError("Scanned PDF detected: the selected pages contain no extractable text. OCR is required.")
            if substantive_words < 50:
                logger.error(
                    f"Selected chapter '{target}' (pages {start_p}–{end_p}) contains only "
                    f"{substantive_words} substantive words ({len(chapter_text)} characters), which is insufficient."
                )
                raise InsufficientSourceContentError(
                    target,
                    substantive_words,
                    f"Extracted pages {start_p}–{end_p} contain only {len(chapter_text)} characters of text."
                )

            combined_content.append(chapter_text)

        result = "\n\n".join(combined_content).strip()
        if not result:
            raise ChapterNotFoundError(chapters[0] if chapters else "unknown", markers)
        return result

    @classmethod
    def extract_chapter_content(cls, full_text: str, chapters: List[str]) -> str:
        """
        Extracts bounded content slices for the requested chapters from raw text.
        Finds start_char of selected chapter and end_char of the next chapter of equal or higher hierarchy.
        """
        markers = cls.parse_text_markers(full_text)
        if not chapters:
            return full_text

        if not markers:
            logger.error("No markers discovered in full text.")
            raise ChapterNotFoundError(chapters[0] if chapters else "unknown", [])

        combined_content = []
        for ch in chapters:
            target = ch.strip()
            if not target:
                continue
            matched = cls.resolve_marker(target, markers)
            if not matched:
                raise ChapterNotFoundError(target, markers)

            start_char = matched.start_char or 0

            # Find next marker of equal or higher hierarchy with start_char > matched.start_char
            next_marker = None
            for m in markers:
                if m.start_char is not None and m.start_char > start_char and m.level <= matched.level:
                    if next_marker is None or m.start_char < next_marker.start_char:
                        next_marker = m

            if next_marker and next_marker.start_char is not None:
                end_char = next_marker.start_char
                next_ch_name = next_marker.number or next_marker.title
                next_info = f"next chapter {next_ch_name} starts at character {end_char}"
            else:
                end_char = len(full_text)
                next_info = "no next chapter marker"

            extracted_slice = full_text[start_char:end_char].strip()

            start_p = matched.start_page or 1
            end_p = matched.end_page or start_p
            total_pages = max(1, end_p - start_p + 1)

            logger.info(
                f"Selected chapter {target}, start page {start_p}, {next_info}, "
                f"extracting pages {start_p}–{end_p}, total pages extracted {total_pages}, "
                f"extracted {len(extracted_slice)} characters"
            )

            if extracted_slice:
                combined_content.append(extracted_slice)

        result = "\n\n".join(combined_content).strip()
        if not result:
            raise ChapterNotFoundError(chapters[0] if chapters else "unknown", markers)
        return result
