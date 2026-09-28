import re
from typing import List, Tuple
from app.core.logger import logger
from app.core.exceptions import InsufficientSourceContentError


class ContentSanitizer:
    """
    Pre-LLM content sanitizer that strictly separates document metadata from actual textbook content.
    Strips document metadata, structural noise, exam specification blocks, page numbers,
    TOC entries, and heading artifacts from extracted text.

    Also performs content sufficiency validation to ensure only substantive educational
    content reaches the LLM.
    """

    # Minimum substantive words required for generating valid academic questions
    MIN_SUBSTANTIVE_WORDS: int = 50

    # Patterns that match metadata/structural lines to be removed
    METADATA_LINE_PATTERNS: List[re.Pattern] = [
        # Page numbers: "Page 1", "- 1 -", "pg. 5", standalone digits
        re.compile(r"^\s*(?:page|pg\.?|p\.)\s*\d+\s*$", re.IGNORECASE),
        re.compile(r"^\s*[-–—]\s*\d+\s*[-–—]\s*$"),
        re.compile(r"^\s*\d{1,4}\s*$"),

        # TOC leader dot lines (e.g. "1.1 Introduction .............. 12")
        re.compile(r"^.*?[\.\-_]{4,}\s*\d+\s*$", re.IGNORECASE),

        # Chapter/section number-only references or heading lines without content
        re.compile(
            r"^\s*(?:chapter|unit|lesson|module|section|part)\s*[:.\-_]?\s*([0-9]+|[ivxlcdm]+)\s*$",
            re.IGNORECASE
        ),
        re.compile(
            r"^\s*(?:see|refer(?:\s+to)?|go\s+to|turn\s+to)\s+(?:chapter|unit|section|module|page|pg\.?)\s*\d+",
            re.IGNORECASE
        ),

        # Document metadata lines
        re.compile(
            r"^\s*(?:document\s+(?:id|version|revision|date|author|title)|"
            r"file\s*(?:name|size|type|format)|"
            r"created\s+(?:on|by|date)|"
            r"modified\s+(?:on|by|date)|"
            r"last\s+(?:updated|modified|saved)|"
            r"copyright|all\s+rights\s+reserved|"
            r"confidential|draft|internal\s+use)\b",
            re.IGNORECASE
        ),

        # Exam specification / blueprint lines
        re.compile(
            r"^\s*(?:total\s+marks?|maximum\s+marks?|time\s*(?:allowed|duration|limit)|\d+\s*marks?)\s*[:=]?\s*\d*",
            re.IGNORECASE
        ),
        re.compile(
            r"^\s*(?:marks?\s*(?:distribution|allocation|breakdown|scheme)|"
            r"question\s*(?:paper\s+)?(?:pattern|format|blueprint|structure|scheme)|"
            r"number\s+of\s+questions?|"
            r"attempt\s+(?:all|any)\s+questions?|"
            r"instructions?\s+(?:to|for)\s+(?:candidates?|students?|examinees?)|"
            r"general\s+instructions?|"
            r"note\s*:\s*(?:all|each|every)\s+questions?\s+(?:are|is)\s+compulsory|"
            r"internal\s+choice|"
            r"section\s*[a-z]?\s*(?:contains?|carries?|has)\s+\d+\s+(?:marks?|questions?)|"
            r"each\s+(?:question|section)\s+carries?\s+\d+\s+marks?)\b",
            re.IGNORECASE
        ),

        # Headers/footers that are repeated structural elements
        re.compile(r"^\s*(?:header|footer|watermark)\s*[:;]", re.IGNORECASE),

        # Printing/publishing artifacts
        re.compile(
            r"^\s*(?:printed\s+(?:by|at|in)|published\s+(?:by|at|in)|"
            r"isbn|edition|reprint|typeset)\b",
            re.IGNORECASE
        ),

        # Segmenter-injected headers (e.g. "--- CONTENT FOR: CHAPTER 5 ---")
        re.compile(r"^---\s*CONTENT\s+FOR.*?---\s*$", re.IGNORECASE),
    ]

    # Block patterns that match multi-line metadata sections to remove entirely
    METADATA_BLOCK_START_PATTERNS: List[re.Pattern] = [
        re.compile(
            r"^\s*(?:general\s+instructions?|instructions?\s+(?:to|for)\s+(?:candidates?|students?))\s*[:.]?\s*$",
            re.IGNORECASE
        ),
        re.compile(
            r"^\s*(?:marks?\s+(?:distribution|allocation|breakdown)|"
            r"question\s+paper\s+(?:design|blueprint|pattern))\s*[:.]?\s*$",
            re.IGNORECASE
        ),
    ]

    @classmethod
    def sanitize(cls, content: str) -> str:
        """
        Removes metadata, structural noise, exam specification content,
        and navigational lines from extracted chapter text before LLM generation.
        Preserves all actual educational subject matter.
        """
        if not content or not content.strip():
            return ""

        original_length = len(content)

        # 1. Remove metadata blocks (multi-line sections)
        cleaned = cls._remove_metadata_blocks(content)

        # 2. Remove individual metadata lines
        cleaned = cls._remove_metadata_lines(cleaned)

        # 3. Collapse excessive whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()

        removed_chars = original_length - len(cleaned)
        if removed_chars > 0:
            logger.info(
                f"[ContentSanitizer] Stripped {removed_chars} chars of metadata/structural noise "
                f"(Cleaned content: {len(cleaned)} chars)."
            )

        return cleaned

    @classmethod
    def _remove_metadata_lines(cls, content: str) -> str:
        """Removes individual lines matching metadata patterns."""
        lines = content.split("\n")
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue

            is_metadata = False
            for pattern in cls.METADATA_LINE_PATTERNS:
                if pattern.search(stripped):
                    is_metadata = True
                    break

            if not is_metadata:
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    @classmethod
    def _remove_metadata_blocks(cls, content: str) -> str:
        """Removes multi-line metadata blocks starting with known headers."""
        lines = content.split("\n")
        cleaned_lines = []
        in_metadata_block = False

        for line in lines:
            stripped = line.strip()

            if not in_metadata_block:
                for pattern in cls.METADATA_BLOCK_START_PATTERNS:
                    if pattern.match(stripped):
                        in_metadata_block = True
                        break

                if not in_metadata_block:
                    cleaned_lines.append(line)
                continue

            if not stripped:
                in_metadata_block = False
                cleaned_lines.append(line)
                continue

            if len(stripped) > 150:
                in_metadata_block = False
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    @classmethod
    def check_sufficiency(cls, content: str, chapter_target: str = "") -> Tuple[bool, int, str]:
        """
        Validates whether sufficient substantive educational content exists.
        Returns: (is_sufficient: bool, substantive_word_count: int, message: str)

        If the content is only titles, headings, TOC entries, page numbers, or metadata,
        it flags it as insufficient so generation can fail fast without hallucinations.
        """
        if not content:
            return False, 0, "No content provided."

        # Extract words with length >= 2
        words = [w for w in re.findall(r"\b[A-Za-z0-9_-]{2,}\b", content) if not w.isdigit()]
        word_count = len(words)

        # Check for presence of explanatory sentences (sentences with 4+ words ending in period/question mark)
        sentences = [
            s.strip() for s in re.split(r"[.!?]\s+", content)
            if len(s.strip().split()) >= 4
        ]

        if word_count < cls.MIN_SUBSTANTIVE_WORDS or len(sentences) < 2:
            msg = (
                f"Selected chapter/topic '{chapter_target}' contains only {word_count} substantive words "
                f"and {len(sentences)} sentence(s). Complete chapter content is required."
            )
            return False, word_count, msg

        return True, word_count, f"Sufficient educational content found ({word_count} substantive words, {len(sentences)} sentences)."

    @classmethod
    def validate_or_raise(cls, content: str, chapter_target: str = "") -> None:
        """Raises InsufficientSourceContentError if content is insufficient."""
        is_sufficient, word_count, msg = cls.check_sufficiency(content, chapter_target)
        if not is_sufficient:
            logger.error(f"[ContentSanitizer] Sufficiency check failed: {msg}")
            raise InsufficientSourceContentError(chapter_target or "selected chapter", substantive_words=word_count)
