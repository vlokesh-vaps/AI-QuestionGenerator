from typing import List, Any


class ChapterNotFoundError(ValueError):
    """
    Raised when a requested chapter or topic cannot be matched to document markers.
    Enforces strict extraction without silent arbitrary fallbacks.
    """
    def __init__(self, target: str, available_markers: List[Any] = None):
        available_markers = available_markers or []
        avail_str = ", ".join(
            f"'{getattr(m, 'number', '')}: {getattr(m, 'title', '')}' (pages {getattr(m, 'start_page', '?')}-{getattr(m, 'end_page', '?')})"
            if getattr(m, 'number', None) else f"'{getattr(m, 'title', '')}' (page {getattr(m, 'start_page', '?')})"
            for m in available_markers[:5]
        )
        msg = (
            f"Requested chapter or topic '{target}' could not be identified in the document markers. "
            f"Discovered markers: [{avail_str if avail_str else 'None'}]."
        )
        super().__init__(msg)
        self.target = target
        self.available_markers = available_markers


class InsufficientSourceContentError(ValueError):
    """
    Raised when the extracted content contains only titles, headings, TOC entries,
    page numbers, or metadata, without sufficient substantive educational content
    to generate rigorous academic examination questions.
    """
    def __init__(self, target: str, substantive_words: int, details: str = ""):
        msg = (
            f"Insufficient substantive educational content in selected chapter/topic '{target}'. "
            f"The extracted content contains only headings, titles, page numbers, or metadata "
            f"({substantive_words} substantive words found). "
            f"Complete educational chapter content is required to generate examination questions without hallucinations. "
            f"{details}".strip()
        )
        super().__init__(msg)
        self.target = target
        self.substantive_words = substantive_words
