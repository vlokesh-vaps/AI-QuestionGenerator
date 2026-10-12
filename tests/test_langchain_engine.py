import pytest
from unittest.mock import MagicMock
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage
from app.services.llm_engine import LLMExamEngine


def test_langchain_engine_init_openai():
    engine = LLMExamEngine(provider="openai", api_key="sk-test-key", model="gpt-4o")
    assert engine.provider == "openai"
    assert engine.model == "gpt-4o"
    assert isinstance(engine.client, ChatOpenAI)
    assert engine.client.model_name == "gpt-4o"


def test_langchain_engine_init_groq():
    engine = LLMExamEngine(provider="groq", api_key="gsk_test_key", model="llama-3.3-70b-versatile")
    assert engine.provider == "groq"
    assert engine.model == "llama-3.3-70b-versatile"
    assert isinstance(engine.client, ChatGroq)


def test_langchain_engine_init_gemini():
    engine = LLMExamEngine(provider="gemini", api_key="gemini_test_key", model="gemini-1.5-flash")
    assert engine.provider == "gemini"
    assert engine.model == "gemini-1.5-flash"
    assert isinstance(engine.client, ChatGoogleGenerativeAI)


def test_langchain_engine_init_nim():
    engine = LLMExamEngine(
        provider="nim",
        api_key="nvapi-test-key",
        model="meta/llama-3.1-70b-instruct",
        base_url="https://integrate.api.nvidia.com/v1"
    )
    assert engine.provider == "nim"
    assert engine.model == "meta/llama-3.1-70b-instruct"
    assert isinstance(engine.client, ChatOpenAI)


def test_langchain_engine_call_provider_chat_mock_string():
    engine = LLMExamEngine(provider="groq", api_key="gsk_dummy", model="llama-3.3-70b-versatile")
    mock_client = MagicMock()
    mock_client.invoke.return_value = AIMessage(content='{"status": "ok", "questions": []}')
    engine.client = mock_client

    content = engine._call_provider_chat("test prompt")
    assert '{"status": "ok"' in content
    assert mock_client.invoke.called


def test_langchain_engine_call_provider_chat_mock_list():
    engine = LLMExamEngine(provider="openai", api_key="sk-dummy", model="gpt-4o-mini")
    mock_client = MagicMock()
    mock_client.invoke.return_value = AIMessage(content=[{"type": "text", "text": '{"result": "success"}'}])
    engine.client = mock_client

    content = engine._call_provider_chat("test prompt")
    assert '{"result": "success"}' in content
    assert mock_client.invoke.called


def test_langchain_engine_missing_key_raises_error():
    engine = LLMExamEngine(provider="openai", api_key="")
    engine.api_key = None
    engine.client = None
    with pytest.raises(ValueError) as excinfo:
        engine._call_provider_chat("test prompt")
    assert "missing" in str(excinfo.value).lower()
