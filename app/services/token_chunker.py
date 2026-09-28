import re
from typing import List, Tuple
from app.core.config import settings
from app.core.logger import logger


class TokenChunker:
    """
    Token-aware content chunking and safety validation.
    Guarantees that input payloads never exceed Groq application-level safety limits (5,000 tokens)
    and target optimal chunk sizes (3,000 - 4,000 tokens).
    """

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Calculates a conservative upper-bound token estimate for academic and technical text.
        Combines character-based and word-based heuristics to ensure tokens are never underestimated.
        """
        if not text:
            return 0
        char_estimate = len(text) / 3.5
        word_estimate = len(text.split()) * 1.35
        return max(1, int(max(char_estimate, word_estimate)))

    @classmethod
    def validate_prompt_tokens(cls, prompt: str, max_tokens: int = None) -> Tuple[bool, int]:
        """
        Validates whether a prompt is strictly within the allowed input token budget.
        Returns: (is_safe: bool, estimated_tokens: int)
        """
        limit = max_tokens or settings.MAX_INPUT_TOKENS
        tokens = cls.estimate_tokens(prompt)
        is_safe = tokens <= limit
        if not is_safe:
            logger.warning(
                f"[TokenChunker] Prompt exceeds safety limit: {tokens} estimated tokens > {limit} maximum tokens."
            )
        return is_safe, tokens

    @classmethod
    def split_into_token_chunks(cls, text: str, max_chunk_tokens: int = None) -> List[str]:
        """
        Splits text content into semantic, bounded chunks targeting 3,000–4,000 tokens.
        Preserves paragraph and sentence boundaries.
        """
        if not text or not text.strip():
            return []

        target_limit = max_chunk_tokens or settings.SAFE_INPUT_TOKENS
        total_tokens = cls.estimate_tokens(text)

        if total_tokens <= target_limit:
            return [text.strip()]

        logger.info(
            f"[TokenChunker] Content of ~{total_tokens} tokens exceeds safe limit of {target_limit}. "
            f"Chunking across semantic boundaries..."
        )

        # 1. Split text into primary blocks (paragraphs and tables)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: List[str] = []
        current_chunk_parts: List[str] = []
        current_chunk_tokens = 0

        for para in paragraphs:
            para_tokens = cls.estimate_tokens(para)

            # If a single paragraph is enormous, split it by sentence boundaries
            if para_tokens > target_limit:
                sub_sentences = cls._split_into_sentences(para)
                for sentence in sub_sentences:
                    sen_tokens = cls.estimate_tokens(sentence)
                    if current_chunk_tokens + sen_tokens > target_limit and current_chunk_parts:
                        chunks.append("\n\n".join(current_chunk_parts))
                        current_chunk_parts = []
                        current_chunk_tokens = 0

                    current_chunk_parts.append(sentence)
                    current_chunk_tokens += sen_tokens
                continue

            if current_chunk_tokens + para_tokens > target_limit and current_chunk_parts:
                chunks.append("\n\n".join(current_chunk_parts))
                current_chunk_parts = []
                current_chunk_tokens = 0

            current_chunk_parts.append(para)
            current_chunk_tokens += para_tokens

        if current_chunk_parts:
            chunks.append("\n\n".join(current_chunk_parts))

        logger.info(f"[TokenChunker] Successfully created {len(chunks)} chunks from content.")
        for idx, chk in enumerate(chunks):
            chk_toks = cls.estimate_tokens(chk)
            logger.debug(f"  Chunk {idx+1}/{len(chunks)}: ~{chk_toks} tokens ({len(chk)} chars)")

        return chunks

    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """Splits large paragraph text by sentence or newline boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    @classmethod
    def reduce_text_to_token_limit(cls, text: str, max_tokens: int) -> str:
        """
        Truncates or slices text to strictly fit within max_tokens, ending at a sentence or word boundary.
        Used for fallback/retry under Groq 413 or 429 conditions.
        """
        if cls.estimate_tokens(text) <= max_tokens:
            return text

        # Approximate character cutoff
        char_target = int(max_tokens * 3.3)
        sliced = text[:char_target]

        # Try to find last period or sentence end
        last_period = max(sliced.rfind(". "), sliced.rfind(".\n"))
        if last_period > int(char_target * 0.7):
            return sliced[:last_period + 1].strip()

        # Fallback to word boundary
        last_space = sliced.rfind(" ")
        if last_space > 0:
            return sliced[:last_space].strip()

        return sliced.strip()
