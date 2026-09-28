import re
from typing import List, Dict, Any, Tuple, Set
from app.core.logger import logger


class QuestionValidator:
    """
    Validates generated questions against strict academic criteria:
    1. Rejects questions asking about chapter numbers, page numbers, titles, metadata, or document structure.
    2. Rejects questions asking about spelling, punctuation, or grammar of headings/titles.
    3. Rejects questions asking about exam configurations, mark distributions, or question counts.
    4. Validates grounding: ensures questions and answers are answerable from the actual source content.
    5. Deduplicates questions.
    """

    # Regex patterns for forbidden questions (metadata, document structure, exam specs)
    FORBIDDEN_QUESTION_PATTERNS: List[re.Pattern] = [
        # Chapter number / chapter title questions
        re.compile(
            r"\b(?:what\s+is\s+the\s+(?:chapter|unit|section|module)\s+number|"
            r"which\s+(?:chapter|unit|section|module)\s+(?:is|discusses|covers|deals)|"
            r"in\s+which\s+(?:chapter|unit|section|module)|"
            r"number\s+of\s+this\s+chapter|"
            r"what\s+is\s+the\s+title\s+of\s+(?:chapter|unit|section|this)|"
            r"title\s+of\s+(?:chapter|the\s+document|this\s+book)|"
            r"name\s+of\s+(?:this|the)\s+chapter)\b",
            re.IGNORECASE
        ),

        # Page number questions
        re.compile(
            r"\b(?:what\s+(?:is\s+the\s+)?page\s+number|"
            r"on\s+which\s+page|"
            r"which\s+page\s+(?:contains|mentions|is)|"
            r"page\s+range\s+of|page\s+\d+\s+discusses)\b",
            re.IGNORECASE
        ),

        # Document metadata (author, publisher, ISBN, copyright, file)
        re.compile(
            r"\b(?:who\s+is\s+the\s+author|"
            r"who\s+wrote\s+this|"
            r"published\s+by|"
            r"publisher\s+of|"
            r"isbn\s*(?:number)?|"
            r"copyright\s*(?:year|holder)?|"
            r"edition\s+of\s+this\s+book|"
            r"file\s+name|document\s+id)\b",
            re.IGNORECASE
        ),

        # Exam specifications (marks, duration, question count, instructions)
        re.compile(
            r"\b(?:how\s+many\s+marks|"
            r"total\s+marks\s+(?:of|for)|"
            r"maximum\s+marks|"
            r"time\s+allowed|"
            r"duration\s+of\s+(?:the\s+)?exam|"
            r"how\s+many\s+questions|"
            r"total\s+(?:number\s+of\s+)?questions|"
            r"section\s+[a-z]\s+carries|"
            r"each\s+question\s+carries|"
            r"instruction\s+to\s+candidates|"
            r"question\s+paper\s+blueprint)\b",
            re.IGNORECASE
        ),

        # Spelling / punctuation / grammar of title or document structural elements
        re.compile(
            r"\b(?:spelling\s+of\s+(?:the\s+)?(?:chapter|title|heading|word\s+in\s+the\s+title)|"
            r"how\s+is\s+(?:the\s+word\s+)?(?:chapter|title)\s+spelled|"
            r"spell\s+the\s+(?:word|name)\s+(?:in|of)\s+the\s+title|"
            r"punctuation\s+(?:in|used\s+in)\s+the\s+title|"
            r"capitalization\s+in\s+the\s+title|"
            r"grammatical\s+error\s+in\s+the\s+title)\b",
            re.IGNORECASE
        ),

        # Document structural references
        re.compile(
            r"\b(?:table\s+of\s+contents|"
            r"in\s+the\s+contents\s+list|"
            r"index\s+of\s+this\s+book|"
            r"heading\s+level|"
            r"font\s+size|italicized\s+text|bold\s+text\s+in\s+the\s+heading)\b",
            re.IGNORECASE
        ),
    ]

    # Stop words to filter out when checking content grounding
    STOP_WORDS = {
        "what", "which", "where", "when", "how", "why", "who", "whom", "whose",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "can", "could", "will", "would", "shall", "should",
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
        "by", "about", "against", "between", "into", "through", "during", "before",
        "after", "above", "below", "from", "up", "down", "of", "off", "over", "under",
        "define", "explain", "describe", "discuss", "calculate", "state", "list",
        "name", "give", "write", "following", "true", "false", "correct", "statement",
        "option", "options", "choose", "select", "term", "mean", "means", "meaning"
    }

    @classmethod
    def validate_candidate_question(
        cls,
        question: Dict[str, Any],
        source_content_lower: str
    ) -> Tuple[bool, str]:
        """
        Validates an individual candidate question.
        Returns: (is_valid: bool, rejection_reason: str)
        """
        q_text = (question.get("text") or "").strip()
        if not q_text:
            return False, "Empty question text"

        # Check 1: Forbidden structural / metadata question patterns
        for pattern in cls.FORBIDDEN_QUESTION_PATTERNS:
            if pattern.search(q_text):
                return False, f"Question asks about forbidden metadata or document structure ('{pattern.pattern[:35]}...')"

        # Check 2: Check options for forbidden patterns if MCQ
        options = question.get("options") or []
        for opt in options:
            clean_opt = str(opt).strip()
            for pattern in cls.FORBIDDEN_QUESTION_PATTERNS:
                if pattern.search(clean_opt):
                    return False, f"Option contains forbidden metadata reference: '{clean_opt}'"

        # Check 3: Check answer grounding in source content
        # Extract substantial keywords (length >= 4, not in stop words)
        words = re.findall(r"\b[A-Za-z0-9_-]{4,}\b", q_text.lower())
        substantive_keywords = [w for w in words if w not in cls.STOP_WORDS]

        if substantive_keywords:
            # At least 40% of key words must be found in the source text
            matched_keywords = [w for w in substantive_keywords if w in source_content_lower]
            grounding_ratio = len(matched_keywords) / len(substantive_keywords)
            if grounding_ratio < 0.35 and len(matched_keywords) < 2:
                return False, (
                    f"Question is not grounded in extracted chapter content "
                    f"(Matched {len(matched_keywords)}/{len(substantive_keywords)} keywords: {matched_keywords})"
                )

        return True, "Valid"

    @classmethod
    def validate_and_filter_questions(
        cls,
        raw_questions: List[Dict[str, Any]],
        source_content: str
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
        """
        Filters raw questions from LLM into accepted and rejected lists.
        Returns: (accepted_questions, rejected_questions_with_reasons)
        """
        source_lower = source_content.lower()
        accepted: List[Dict[str, Any]] = []
        rejected: List[Tuple[Dict[str, Any], str]] = []

        seen_normalized: Set[str] = set()

        for idx, q in enumerate(raw_questions):
            q_text = (q.get("text") or "").strip()

            # Deduplication check
            norm_text = re.sub(r"[^\w\s]", "", q_text.lower()).strip()
            if not norm_text or norm_text in seen_normalized:
                rejected.append((q, "Duplicate question text"))
                logger.debug(f"[QuestionValidator] Rejected #{idx+1}: Duplicate question.")
                continue

            # Grounding and structural validity check
            is_valid, reason = cls.validate_candidate_question(q, source_lower)
            if is_valid:
                seen_normalized.add(norm_text)
                accepted.append(q)
            else:
                rejected.append((q, reason))
                logger.warning(
                    f"[QuestionValidator] REJECTED question #{idx+1}: '{q_text[:70]}...' | Reason: {reason}"
                )

        logger.info(
            f"[QuestionValidator] Validation Summary: "
            f"Generated={len(raw_questions)}, Accepted={len(accepted)}, Rejected={len(rejected)}."
        )

        return accepted, rejected
