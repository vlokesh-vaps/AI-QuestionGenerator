import os
from pathlib import Path
from typing import Dict, List, Optional
from app.core.config import settings
from app.core.logger import logger

# Canonical default models per provider
DEFAULT_MODELS: Dict[str, str] = {
    "groq": "qwen/qwen3.8-27b",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "nim": "meta/llama-3.1-70b-instruct",
}

# Mapping of provider to environment variable names
PROVIDER_ENV_MAP: Dict[str, Dict[str, str]] = {
    "groq": {
        "key": "GROQ_API_KEY",
        "model": "GROQ_MODEL",
    },
    "openai": {
        "key": "OPENAI_API_KEY",
        "model": "OPENAI_MODEL",
    },
    "gemini": {
        "key": "GEMINI_API_KEY",
        "model": "GEMINI_MODEL",
    },
    "nim": {
        "key": "NIM_API_KEY",
        "model": "NIM_MODEL",
        "base_url": "NIM_BASE_URL",
    },
}


class EnvManager:
    """
    Manager for atomic CRUD operations on the project .env file,
    ensuring synchronization with in-memory pydantic settings and os.environ.
    """

    @staticmethod
    def get_env_path() -> Path:
        env_path = settings.BASE_DIR / ".env"
        if not env_path.exists():
            example_path = settings.BASE_DIR / ".env.example"
            if example_path.exists():
                try:
                    with open(example_path, "r", encoding="utf-8") as src, open(env_path, "w", encoding="utf-8") as dst:
                        dst.write(src.read())
                except Exception as e:
                    logger.warning(f"[EnvManager] Could not copy .env.example: {e}")
        return env_path

    @classmethod
    def read_all_keys(cls) -> Dict[str, str]:
        """Reads all non-comment key-value pairs from .env file."""
        env_path = cls.get_env_path()
        result: Dict[str, str] = {}
        if not env_path.exists():
            return result

        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        k, v = stripped.split("=", 1)
                        result[k.strip()] = v.strip().strip("'\"")
        except Exception as e:
            logger.error(f"[EnvManager] Error reading .env: {e}")
        return result

    @classmethod
    def set_keys(cls, updates: Dict[str, str]) -> bool:
        """
        Creates or updates keys in the .env file in-place, preserving comments and structure.
        Also updates os.environ and in-memory settings attributes.
        """
        if not updates:
            return True

        env_path = cls.get_env_path()
        lines: List[str] = []
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                logger.error(f"[EnvManager] Could not read lines from {env_path}: {e}")

        existing_keys = set()
        new_lines: List[str] = []

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

        # Append any new keys that were not in the file
        for k, v in updates.items():
            if k not in existing_keys:
                new_lines.append(f"{k}={v}\n")

            # Sync os.environ and runtime settings
            os.environ[k] = str(v)
            if hasattr(settings, k):
                try:
                    setattr(settings, k, v)
                except Exception as ex:
                    logger.warning(f"[EnvManager] Failed updating settings.{k}: {ex}")

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            logger.info(f"[EnvManager] Successfully updated {len(updates)} keys in {env_path}.")
            return True
        except Exception as e:
            logger.error(f"[EnvManager] Failed writing updates to .env: {e}")
            return False

    @classmethod
    def delete_keys(cls, keys: List[str], remove_line: bool = False) -> bool:
        """
        Deletes or blanks keys from the .env file.
        If remove_line=True, the line is removed completely.
        If remove_line=False (default), it sets KEY= (blank) to preserve file structure.
        Also clears from os.environ and resets runtime settings.
        """
        if not keys:
            return True

        target_set = set(keys)
        env_path = cls.get_env_path()
        lines: List[str] = []
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                logger.error(f"[EnvManager] Could not read .env: {e}")

        new_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                k = k.strip()
                if k in target_set:
                    if not remove_line:
                        new_lines.append(f"{k}=\n")
                    # if remove_line is True, we drop the line completely
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Sync os.environ and runtime settings
        for k in keys:
            os.environ[k] = ""
            if hasattr(settings, k):
                try:
                    setattr(settings, k, "")
                except Exception as ex:
                    logger.warning(f"[EnvManager] Failed resetting settings.{k}: {ex}")

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            logger.info(f"[EnvManager] Successfully deleted/cleared {len(keys)} keys from {env_path}.")
            return True
        except Exception as e:
            logger.error(f"[EnvManager] Failed writing deletions to .env: {e}")
            return False

    @classmethod
    def delete_provider_key(cls, provider: str) -> bool:
        """Deletes/blanks out the API key for a specified provider."""
        prov = provider.lower().strip()
        info = PROVIDER_ENV_MAP.get(prov)
        if not info or "key" not in info:
            raise ValueError(f"Unknown provider '{provider}'")
        key_var = info["key"]
        return cls.delete_keys([key_var], remove_line=False)

    @classmethod
    def reset_provider_model(cls, provider: str) -> str:
        """Resets the model for a provider back to its default recommended model."""
        prov = provider.lower().strip()
        info = PROVIDER_ENV_MAP.get(prov)
        if not info or "model" not in info or prov not in DEFAULT_MODELS:
            raise ValueError(f"Unknown provider '{provider}'")
        default_model = DEFAULT_MODELS[prov]
        model_var = info["model"]
        cls.set_keys({model_var: default_model})
        return default_model
