from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from evaluation import client


def _response(*texts):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        stop_reason="end_turn",
    )


def test_call_model_returns_concatenated_text_blocks():
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    fake_client.messages.create.return_value = _response("hello", " world")

    with patch.object(client, "get_client", return_value=fake_client):
        result = client.call_model("system", "user", max_tokens=64)

    assert result == "hello world"
    fake_client.messages.create.assert_called_once_with(
        model=client.settings.MODEL_NAME,
        max_tokens=64,
        system="system",
        messages=[{"role": "user", "content": "user"}],
    )


def test_call_model_raises_when_response_has_no_text():
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", text="ignored")],
        stop_reason="end_turn",
    )

    with patch.object(client, "get_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="no text content"):
            client.call_model("system", "user")


def test_get_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(client.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(client, "_client", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client.get_client()
