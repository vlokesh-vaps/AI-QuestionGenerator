from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ProviderConfigItem(BaseModel):
    configured: bool
    model: str
    masked_key: Optional[str] = None
    base_url: Optional[str] = None


class LLMConfigResponse(BaseModel):
    active_provider: str
    providers: Dict[str, ProviderConfigItem]


class UpdateLLMConfigRequest(BaseModel):
    active_provider: Optional[str] = Field(None, description="'groq' | 'openai' | 'gemini' | 'nim'")
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    nim_api_key: Optional[str] = None
    nim_base_url: Optional[str] = None
    nim_model: Optional[str] = None


class TestConnectionRequest(BaseModel):
    provider: str = Field(..., description="'groq' | 'openai' | 'gemini' | 'nim'")
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool
    provider: str
    model: str
    message: str
    details: Optional[str] = None
