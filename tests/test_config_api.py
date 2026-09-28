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
