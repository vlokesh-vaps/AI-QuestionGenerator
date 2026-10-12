from typing import Dict, Optional
from fastapi import APIRouter, HTTPException
from app.core.config import settings
from app.core.logger import logger
from app.schemas.llm_config import (
    LLMConfigResponse,
    ProviderConfigItem,
    UpdateLLMConfigRequest,
    TestConnectionRequest,
    TestConnectionResponse,
    DeleteKeyResponse,
    ResetModelResponse
)
from app.services.llm_engine import LLMExamEngine
from app.services.env_manager import EnvManager, DEFAULT_MODELS

router = APIRouter()


def _is_valid_key(key: Optional[str]) -> bool:
    if not key:
        return False
    k = key.strip().lower()
    if not k or "your_" in k or "_here" in k:
        return False
    return True


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not _is_valid_key(key):
        return None
    k = key.strip()
    if len(k) <= 8:
        return "****"
    return k[:6] + "..." + k[-4:]


@router.get("/config/llm", response_model=LLMConfigResponse, summary="Get LLM providers configuration status")
def get_llm_config():
    """Returns the currently active provider and configuration status for all 4 LLM providers."""
    providers = {
        "groq": ProviderConfigItem(
            configured=_is_valid_key(settings.GROQ_API_KEY),
            model=settings.GROQ_MODEL,
            masked_key=_mask_key(settings.GROQ_API_KEY),
            api_key=settings.GROQ_API_KEY if _is_valid_key(settings.GROQ_API_KEY) else None
        ),
        "openai": ProviderConfigItem(
            configured=_is_valid_key(settings.OPENAI_API_KEY),
            model=settings.OPENAI_MODEL,
            masked_key=_mask_key(settings.OPENAI_API_KEY),
            api_key=settings.OPENAI_API_KEY if _is_valid_key(settings.OPENAI_API_KEY) else None
        ),
        "gemini": ProviderConfigItem(
            configured=_is_valid_key(settings.GEMINI_API_KEY),
            model=settings.GEMINI_MODEL,
            masked_key=_mask_key(settings.GEMINI_API_KEY),
            api_key=settings.GEMINI_API_KEY if _is_valid_key(settings.GEMINI_API_KEY) else None
        ),
        "nim": ProviderConfigItem(
            configured=_is_valid_key(settings.NIM_API_KEY),
            model=settings.NIM_MODEL,
            masked_key=_mask_key(settings.NIM_API_KEY),
            api_key=settings.NIM_API_KEY if _is_valid_key(settings.NIM_API_KEY) else None,
            base_url=settings.NIM_BASE_URL
        )
    }

    return LLMConfigResponse(
        active_provider=settings.LLM_PROVIDER,
        providers=providers
    )


@router.post("/config/llm", response_model=LLMConfigResponse, summary="Update LLM credentials and active provider")
def update_llm_config(req: UpdateLLMConfigRequest):
    """
    Updates active provider, models, and API keys.
    Updates in-memory settings and persists changes to the `.env` file via EnvManager.
    """
    env_updates: Dict[str, str] = {}
    keys_to_delete: list = []

    if req.active_provider:
        prov = req.active_provider.lower().strip()
        if prov not in ["groq", "openai", "gemini", "nim"]:
            raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq', 'openai', 'gemini', or 'nim'.")
        env_updates["LLM_PROVIDER"] = prov

    # Groq
    if req.groq_api_key is not None:
        clean_key = req.groq_api_key.strip()
        if clean_key:
            env_updates["GROQ_API_KEY"] = clean_key
        else:
            keys_to_delete.append("GROQ_API_KEY")
    if req.groq_model is not None and req.groq_model.strip():
        env_updates["GROQ_MODEL"] = req.groq_model.strip()

    # OpenAI
    if req.openai_api_key is not None:
        clean_key = req.openai_api_key.strip()
        if clean_key:
            env_updates["OPENAI_API_KEY"] = clean_key
        else:
            keys_to_delete.append("OPENAI_API_KEY")
    if req.openai_model is not None and req.openai_model.strip():
        env_updates["OPENAI_MODEL"] = req.openai_model.strip()

    # Gemini
    if req.gemini_api_key is not None:
        clean_key = req.gemini_api_key.strip()
        if clean_key:
            env_updates["GEMINI_API_KEY"] = clean_key
        else:
            keys_to_delete.append("GEMINI_API_KEY")
    if req.gemini_model is not None and req.gemini_model.strip():
        env_updates["GEMINI_MODEL"] = req.gemini_model.strip()

    # NIM
    if req.nim_api_key is not None:
        clean_key = req.nim_api_key.strip()
        if clean_key:
            env_updates["NIM_API_KEY"] = clean_key
        else:
            keys_to_delete.append("NIM_API_KEY")
    if req.nim_model is not None and req.nim_model.strip():
        env_updates["NIM_MODEL"] = req.nim_model.strip()
    if req.nim_base_url is not None and req.nim_base_url.strip():
        env_updates["NIM_BASE_URL"] = req.nim_base_url.strip()

    if env_updates:
        EnvManager.set_keys(env_updates)

    if keys_to_delete:
        EnvManager.delete_keys(keys_to_delete, remove_line=False)

    return get_llm_config()


@router.delete("/config/llm/{provider}/key", response_model=DeleteKeyResponse, summary="Delete / Clear an LLM provider API key from .env")
def delete_llm_provider_key(provider: str):
    """
    Deletes/blanks out the stored API key for the specified provider from the .env file and resets in-memory credentials.
    """
    prov = provider.lower().strip()
    if prov not in ["groq", "openai", "gemini", "nim"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq', 'openai', 'gemini', or 'nim'.")

    try:
        EnvManager.delete_provider_key(prov)
        return DeleteKeyResponse(
            success=True,
            provider=prov,
            message=f"Successfully deleted {prov.upper()} API key from .env."
        )
    except Exception as e:
        logger.error(f"[Delete Key] Failed for {prov}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/llm/{provider}/reset-model", response_model=ResetModelResponse, summary="Reset provider model to default")
def reset_llm_provider_model(provider: str):
    """
    Resets the model identifier for the specified provider back to its default recommended setting in .env.
    """
    prov = provider.lower().strip()
    if prov not in ["groq", "openai", "gemini", "nim"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq', 'openai', 'gemini', or 'nim'.")

    try:
        default_model = EnvManager.reset_provider_model(prov)
        return ResetModelResponse(
            success=True,
            provider=prov,
            model=default_model,
            message=f"Reset {prov.upper()} model to default: {default_model}"
        )
    except Exception as e:
        logger.error(f"[Reset Model] Failed for {prov}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/config/llm/test", response_model=TestConnectionResponse, summary="Test connection to an LLM provider")
def test_llm_connection(req: TestConnectionRequest):
    """
    Sends a lightweight ping prompt to the specified provider and verifies credentials and model accessibility.
    """
    prov = req.provider.lower().strip()
    if prov not in ["groq", "openai", "gemini", "nim"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq', 'openai', 'gemini', or 'nim'.")

    try:
        engine = LLMExamEngine(
            provider=prov,
            api_key=req.api_key or None,
            model=req.model or None,
            base_url=req.base_url or None
        )

        test_prompt = (
            "You are a connection diagnostic test. "
            "Respond strictly with valid JSON: {\"status\": \"ok\", \"message\": \"connection successful\"}"
        )
        content = engine._call_provider_chat(test_prompt)

        return TestConnectionResponse(
            success=True,
            provider=engine.provider,
            model=engine.model,
            message=f"Successfully connected to {engine.provider.upper()} ({engine.model})!",
            details=content[:100]
        )

    except Exception as e:
        logger.error(f"[Test Connection] Failed for {prov}: {e}", exc_info=True)
        return TestConnectionResponse(
            success=False,
            provider=prov,
            model=req.model or "default",
            message=f"Connection failed: {str(e)}",
            details=str(e)
        )
