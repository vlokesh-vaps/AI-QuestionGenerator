import os
import shutil
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Question Paper Generator"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Base Directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    EXPORTS_DIR: Path = STORAGE_DIR / "exports"
    UPLOADS_DIR: Path = STORAGE_DIR / "uploads"
    MARKER_CACHE_DIR: Path = STORAGE_DIR / "marker_cache"
    
    # Active LLM Provider Selection: 'groq' | 'openai' | 'gemini' | 'nim'
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq").lower()

    # Groq API Credentials
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "") or os.getenv("paper_Groq_api_key", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    # OpenAI API Credentials
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Google Gemini API Credentials
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # NVIDIA NIM API Credentials (OpenAI-compatible)
    NIM_API_KEY: str = os.getenv("NIM_API_KEY", "") or os.getenv("NVIDIA_API_KEY", "")
    NIM_BASE_URL: str = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    NIM_MODEL: str = os.getenv("NIM_MODEL", "meta/llama-3.1-70b-instruct")

    LLM_MAX_RETRIES: int = 3
    GROQ_MAX_RETRIES: int = 3
    
    # Token Safety & Chunking Limits (Strictly prevents Groq 413 / ITPM limits)
    MAX_INPUT_TOKENS: int = 5000     # Hard application-level safety limit per Groq request
    SAFE_INPUT_TOKENS: int = 3500    # Target chunk token budget (3,000 - 4,000)
    CHUNK_SIZE: int = 3000           # Target chunk size in tokens
    
    # Document Scale Limits
    MAX_FILE_SIZE_MB: int = 50       # Supports DOCX files up to 50 MB
    MAX_PDF_PAGES: int = 500         # Supports PDFs up to 500 pages
    MAX_QUESTION_PAPER_MARKS: int = 1000  # Supports up to 1,000 total marks for final paper
    
    # CORS Configuration
    CORS_ORIGINS: List[str] = ["*"]
    
    # Generation parameters
    MAX_CONTEXT_CHARS: int = 50000
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()


def reset_runtime_storage() -> None:
    """Clear generated runtime data and recreate the required directories.

    Runtime uploads, generated papers, and marker indexes are disposable. The
    cleanup is restricted to these three known child directories; it never
    removes the storage root or any source-code directory.
    """
    runtime_dirs = (
        settings.EXPORTS_DIR,
        settings.UPLOADS_DIR,
        settings.MARKER_CACHE_DIR,
    )
    settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    for directory in runtime_dirs:
        if directory.exists():
            if directory.is_dir():
                shutil.rmtree(directory)
            else:
                directory.unlink()
        directory.mkdir(parents=True, exist_ok=True)


reset_runtime_storage()
