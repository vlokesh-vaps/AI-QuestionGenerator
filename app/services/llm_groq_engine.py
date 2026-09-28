"""
Backward-compatible wrapper for GroqExamEngine.
Delegates to the unified multi-provider LLMExamEngine.
"""
from app.services.llm_engine import LLMExamEngine, GroqExamEngine

__all__ = ["GroqExamEngine", "LLMExamEngine"]
