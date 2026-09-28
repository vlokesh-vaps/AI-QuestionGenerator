from typing import Dict, Optional
from fastapi import APIRouter, HTTPException
from app.core.config import settings
from app.core.logger import logger
from app.schemas.llm_config import (
    LLMConfigResponse,
    ProviderConfigItem,
    UpdateLLMConfigRequest,
    TestConnectionRequest,
    TestConnectionResponse
)
from app.services.llm_engine import LLMExamEngine

router = APIRouter()


def _mask_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    k = key.strip()
    if len(k) <= 8:
        return "****"
    return k[:6] + "..." + k[-4:]


def _update_env_file(updates: Dict[str, str]):
    env_path = settings.BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    existing_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                existing_keys.add(k)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@router.get("/config/llm", response_model=LLMConfigResponse, summary="Get LLM providers configuration status")
def get_llm_config():
    """Returns the currently active provider and configuration status for all 4 LLM providers."""
    providers = {
        "groq": ProviderConfigItem(
            configured=bool(settings.GROQ_API_KEY),
            model=settings.GROQ_MODEL,
            masked_key=_mask_key(settings.GROQ_API_KEY)
        ),
        "openai": ProviderConfigItem(
            configured=bool(settings.OPENAI_API_KEY),
            model=settings.OPENAI_MODEL,
            masked_key=_mask_key(settings.OPENAI_API_KEY)
        ),
        "gemini": ProviderConfigItem(
            configured=bool(settings.GEMINI_API_KEY),
            model=settings.GEMINI_MODEL,
            masked_key=_mask_key(settings.GEMINI_API_KEY)
        ),
        "nim": ProviderConfigItem(
            configured=bool(settings.NIM_API_KEY),
            model=settings.NIM_MODEL,
            masked_key=_mask_key(settings.NIM_API_KEY),
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
    Updates in-memory settings and persists changes to the `.env` file.
    """
    env_updates: Dict[str, str] = {}

    if req.active_provider:
        prov = req.active_provider.lower().strip()
        if prov not in ["groq", "openai", "gemini", "nim"]:
            raise HTTPException(status_code=400, detail="Invalid provider. Must be 'groq', 'openai', 'gemini', or 'nim'.")
        settings.LLM_PROVIDER = prov
        env_updates["LLM_PROVIDER"] = prov

    if req.groq_api_key is not None:
        settings.GROQ_API_KEY = req.groq_api_key.strip()
        env_updates["GROQ_API_KEY"] = settings.GROQ_API_KEY
    if req.groq_model is not None and req.groq_model.strip():
        settings.GROQ_MODEL = req.groq_model.strip()
        env_updates["GROQ_MODEL"] = settings.GROQ_MODEL

    if req.openai_api_key is not None:
        settings.OPENAI_API_KEY = req.openai_api_key.strip()
        env_updates["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if req.openai_model is not None and req.openai_model.strip():
        settings.OPENAI_MODEL = req.openai_model.strip()
        env_updates["OPENAI_MODEL"] = settings.OPENAI_MODEL

    if req.gemini_api_key is not None:
        settings.GEMINI_API_KEY = req.gemini_api_key.strip()
        env_updates["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
    if req.gemini_model is not None and req.gemini_model.strip():
        settings.GEMINI_MODEL = req.gemini_model.strip()
        env_updates["GEMINI_MODEL"] = settings.GEMINI_MODEL

    if req.nim_api_key is not None:
        settings.NIM_API_KEY = req.nim_api_key.strip()
        env_updates["NIM_API_KEY"] = settings.NIM_API_KEY
    if req.nim_model is not None and req.nim_model.strip():
        settings.NIM_MODEL = req.nim_model.strip()
        env_updates["NIM_MODEL"] = settings.NIM_MODEL
    if req.nim_base_url is not None and req.nim_base_url.strip():
        settings.NIM_BASE_URL = req.nim_base_url.strip()
        env_updates["NIM_BASE_URL"] = settings.NIM_BASE_URL

    if env_updates:
        try:
            _update_env_file(env_updates)
            logger.info(f"[Config API] Updated and persisted {len(env_updates)} settings to .env.")
        except Exception as e:
            logger.warning(f"[Config API] Could not write to .env: {e}")

    return get_llm_config()


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
