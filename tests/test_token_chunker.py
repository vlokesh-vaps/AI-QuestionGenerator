import pytest
from app.core.config import settings
from app.services.token_chunker import TokenChunker


def test_token_estimation():
    short_text = "What is the second law of thermodynamics?"
    tokens = TokenChunker.estimate_tokens(short_text)
    assert 5 <= tokens <= 20

    # 10,000 characters of text
    long_text = "This is a sentence explaining physics. " * 300
    long_tokens = TokenChunker.estimate_tokens(long_text)
    assert long_tokens > 2000
    assert long_tokens < 4500


def test_validate_prompt_tokens_hard_limit():
    safe_text = "Word " * 2000
    is_safe, tokens = TokenChunker.validate_prompt_tokens(safe_text, max_tokens=5000)
    assert is_safe is True
    assert tokens <= 5000

    oversized_text = "Word " * 6000
    is_safe_over, tokens_over = TokenChunker.validate_prompt_tokens(oversized_text, max_tokens=5000)
    assert is_safe_over is False
    assert tokens_over > 5000


def test_split_into_token_chunks():
    # Construct multi-paragraph text totaling ~8,000 tokens
    paragraphs = [f"Paragraph {i}: " + ("Newton formulated the laws of gravitation and mechanics. " * 30) for i in range(25)]
    full_content = "\n\n".join(paragraphs)

    total_tokens = TokenChunker.estimate_tokens(full_content)
    assert total_tokens > 5000

    # Split into chunks targeting SAFE_INPUT_TOKENS (e.g. 3,500)
    chunks = TokenChunker.split_into_token_chunks(full_content, max_chunk_tokens=3500)
    assert len(chunks) >= 2

    # Verify each chunk is strictly within the safe limit
    for chunk in chunks:
        chk_tokens = TokenChunker.estimate_tokens(chunk)
        assert chk_tokens <= 3500


def test_reduce_text_to_token_limit():
    text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
    reduced = TokenChunker.reduce_text_to_token_limit(text, max_tokens=8)
    assert TokenChunker.estimate_tokens(reduced) <= 8
    assert len(reduced) < len(text)
