import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)

def test_get_llm_config():
    response = client.get("/api/v1/config/llm")
    assert response.status_code == 200
    data = response.json()
    assert "active_provider" in data
    assert "providers" in data
    assert "groq" in data["providers"]
    assert "openai" in data["providers"]
    assert "gemini" in data["providers"]
    assert "nim" in data["providers"]

def test_update_llm_config_invalid_provider():
    response = client.post("/api/v1/config/llm", json={"active_provider": "unsupported_provider"})
    assert response.status_code == 400
    assert "Invalid provider" in response.json()["detail"]

def test_update_llm_config_valid():
    original_provider = settings.LLM_PROVIDER
    try:
        response = client.post(
            "/api/v1/config/llm",
            json={
                "active_provider": "nim",
                "nim_model": "meta/llama-3.1-70b-instruct",
                "nim_base_url": "https://integrate.api.nvidia.com/v1"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["active_provider"] == "nim"
        assert data["providers"]["nim"]["model"] == "meta/llama-3.1-70b-instruct"
        assert data["providers"]["nim"]["base_url"] == "https://integrate.api.nvidia.com/v1"
    finally:
        # Restore original provider
        client.post("/api/v1/config/llm", json={"active_provider": original_provider})

def test_test_connection_invalid_provider():
    response = client.post(
        "/api/v1/config/llm/test",
        json={"provider": "invalid_provider", "api_key": "test_key"}
    )
    assert response.status_code == 400

def test_test_connection_handled_failure():
    # Calling test with an invalid dummy key should return handled failure with 200 and success=False
    response = client.post(
        "/api/v1/config/llm/test",
        json={
            "provider": "openai",
            "api_key": "sk-invalid-test-key-12345678",
            "model": "gpt-4o-mini"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "failed" in data["message"].lower() or "error" in data["message"].lower()


def test_delete_llm_provider_key():
    # 1. First set a key for openai
    client.post("/api/v1/config/llm", json={"openai_api_key": "sk-test-openai-temporary-1234"})
    res = client.get("/api/v1/config/llm")
    assert res.json()["providers"]["openai"]["configured"] is True

    # 2. Delete the key
    del_res = client.delete("/api/v1/config/llm/openai/key")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # 3. Check that it is now unconfigured
    res2 = client.get("/api/v1/config/llm")
    assert res2.json()["providers"]["openai"]["configured"] is False
    assert res2.json()["providers"]["openai"]["masked_key"] is None


def test_reset_llm_provider_model():
    # 1. Update model to custom
    client.post("/api/v1/config/llm", json={"groq_model": "custom-model-identifier"})
    res = client.get("/api/v1/config/llm")
    assert res.json()["providers"]["groq"]["model"] == "custom-model-identifier"

    # 2. Reset back to default
    reset_res = client.post("/api/v1/config/llm/groq/reset-model")
    assert reset_res.status_code == 200
    assert reset_res.json()["model"] == "qwen/qwen3.8-27b"

    # 3. Verify in config
    res2 = client.get("/api/v1/config/llm")
    assert res2.json()["providers"]["groq"]["model"] == "qwen/qwen3.8-27b"


def test_env_manager_crud():
    from app.services.env_manager import EnvManager
    
    # Create / Update
    EnvManager.set_keys({"TEST_CUSTOM_KEY": "sample_val_123"})
    all_keys = EnvManager.read_all_keys()
    assert all_keys.get("TEST_CUSTOM_KEY") == "sample_val_123"

    # Update
    EnvManager.set_keys({"TEST_CUSTOM_KEY": "updated_val_456"})
    all_keys2 = EnvManager.read_all_keys()
    assert all_keys2.get("TEST_CUSTOM_KEY") == "updated_val_456"

    # Delete
    EnvManager.delete_keys(["TEST_CUSTOM_KEY"], remove_line=True)
    all_keys3 = EnvManager.read_all_keys()
    assert "TEST_CUSTOM_KEY" not in all_keys3
