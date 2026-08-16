from types import SimpleNamespace
from unittest.mock import Mock, patch

import anthropic
import httpx
import pytest

from evaluation import client


def _response(*texts, input_tokens=1200, output_tokens=340):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


def test_call_model_returns_concatenated_text_blocks():
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    fake_client.messages.create.return_value = _response("hello", " world")

    with patch.object(client, "get_client", return_value=fake_client):
        result = client.call_model("system", "user", max_tokens=64)

    assert result.text == "hello world"
    fake_client.messages.create.assert_called_once_with(
        model=client.settings.MODEL_NAME,
        max_tokens=64,
        system="system",
        messages=[{"role": "user", "content": "user"}],
    )


def test_call_model_surfaces_token_usage():
    # The whole point of the ModelResponse wrapper: usage reaches the caller
    # instead of being dropped with the SDK response object.
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    fake_client.messages.create.return_value = _response(
        "ok", input_tokens=2480, output_tokens=317
    )

    with patch.object(client, "get_client", return_value=fake_client):
        result = client.call_model("system", "user")

    assert result.input_tokens == 2480
    assert result.output_tokens == 317
    # The configured alias, not whatever snapshot id the API echoes — the
    # price table is keyed on the alias.
    assert result.model_name == client.settings.MODEL_NAME


def test_call_model_raises_when_response_has_no_text():
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock()))
    fake_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", text="ignored")],
        stop_reason="end_turn",
    )

    with patch.object(client, "get_client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="no text content"):
            client.call_model("system", "user")


def _connection_error():
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )


def test_call_model_retries_on_transient_error(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(
        side_effect=[_connection_error(), _response("recovered")]
    )))
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with patch.object(client, "get_client", return_value=fake_client):
        result = client.call_model("system", "user")

    assert result.text == "recovered"
    assert fake_client.messages.create.call_count == 2


def test_call_model_raises_after_max_retries(monkeypatch):
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=Mock(
        side_effect=_connection_error()
    )))
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with patch.object(client, "get_client", return_value=fake_client):
        with pytest.raises(anthropic.APIConnectionError):
            client.call_model("system", "user")

    assert fake_client.messages.create.call_count == client.MAX_ATTEMPTS


def test_get_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(client.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(client, "_client", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client.get_client()
