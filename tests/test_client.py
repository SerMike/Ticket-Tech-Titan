from types import SimpleNamespace
from unittest.mock import Mock, patch

import anthropic
import httpx
import httpx2
import openai
import pytest

from config import settings
from evaluation import client


@pytest.fixture(autouse=True)
def _no_cached_provider(monkeypatch):
    # get_provider() caches the adapter it builds; every test starts without one.
    monkeypatch.setattr(client, "_provider", None)


def _via(provider):
    """Route call_model() through `provider` for the duration of a test."""
    return patch.object(client, "get_provider", return_value=provider)


# ---------------------------------------------------------------------------
# Anthropic adapter (the default)
# ---------------------------------------------------------------------------

def _response(*texts, input_tokens=1200, output_tokens=340):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        ),
    )


def _anthropic(create):
    return client.AnthropicProvider(SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_call_model_returns_concatenated_text_blocks():
    create = Mock(return_value=_response("hello", " world"))

    with _via(_anthropic(create)):
        result = client.call_model("system", "user", max_tokens=64)

    assert result.text == "hello world"
    create.assert_called_once_with(
        model=client.settings.MODEL_NAME,
        max_tokens=64,
        system="system",
        messages=[{"role": "user", "content": "user"}],
    )


def test_call_model_surfaces_token_usage():
    # The whole point of the ModelResponse wrapper: usage reaches the caller
    # instead of being dropped with the SDK response object.
    create = Mock(return_value=_response("ok", input_tokens=2480, output_tokens=317))

    with _via(_anthropic(create)):
        result = client.call_model("system", "user")

    assert result.input_tokens == 2480
    assert result.output_tokens == 317
    # The configured alias, not whatever snapshot id the API echoes — the
    # price table is keyed on the alias.
    assert result.model_name == client.settings.MODEL_NAME


def test_call_model_raises_when_response_has_no_text():
    create = Mock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", text="ignored")],
        stop_reason="end_turn",
    ))

    with _via(_anthropic(create)):
        with pytest.raises(RuntimeError, match="no text content"):
            client.call_model("system", "user")


def _connection_error():
    return anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com")
    )


def test_call_model_retries_on_transient_error(monkeypatch):
    create = Mock(side_effect=[_connection_error(), _response("recovered")])
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with _via(_anthropic(create)):
        result = client.call_model("system", "user")

    assert result.text == "recovered"
    assert create.call_count == 2


def test_call_model_raises_after_max_retries(monkeypatch):
    create = Mock(side_effect=_connection_error())
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with _via(_anthropic(create)):
        with pytest.raises(anthropic.APIConnectionError):
            client.call_model("system", "user")

    assert create.call_count == client.MAX_ATTEMPTS


def test_anthropic_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        client.get_provider()


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter
# ---------------------------------------------------------------------------

def _completion(text="hello", *, finish_reason="stop", usage=(2480, 190)):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=text), finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None,
    )


def _openai(create):
    return client.OpenAICompatProvider(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )


def _openai_status_error(cls, status):
    # The openai SDK builds its errors on httpx2, not the httpx anthropic uses.
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("boom", response=httpx2.Response(status, request=request), body=None)


def test_openai_sends_the_system_prompt_as_the_first_message(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_NAME", "gpt-test")
    create = Mock(return_value=_completion("hello"))

    with _via(_openai(create)):
        result = client.call_model("system", "user", max_tokens=64)

    assert result.text == "hello"
    create.assert_called_once_with(
        model="gpt-test",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        max_completion_tokens=64,
    )


def test_openai_usage_maps_onto_the_shared_contract(monkeypatch):
    # prompt/completion tokens become input/output, so cost tracking stays
    # provider-agnostic; the configured alias is recorded as the model.
    monkeypatch.setattr(settings, "MODEL_NAME", "gpt-test")
    create = Mock(return_value=_completion(usage=(3100, 210)))

    with _via(_openai(create)):
        result = client.call_model("system", "user")

    assert (result.input_tokens, result.output_tokens) == (3100, 210)
    assert result.model_name == "gpt-test"


def test_openai_without_usage_is_untracked_not_zero():
    create = Mock(return_value=_completion(usage=None))

    with _via(_openai(create)):
        result = client.call_model("system", "user")

    assert (result.input_tokens, result.output_tokens) == (None, None)


def test_openai_empty_reply_names_the_finish_reason():
    create = Mock(return_value=_completion(None, finish_reason="length"))

    with _via(_openai(create)):
        with pytest.raises(RuntimeError, match="no text content. Finish reason: length.*reasoning"):
            client.call_model("system", "user")


def test_openai_retries_rate_limits_and_server_errors(monkeypatch):
    create = Mock(side_effect=[
        _openai_status_error(openai.RateLimitError, 429),
        _openai_status_error(openai.InternalServerError, 503),
        openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com")),
        _completion("recovered"),
    ])
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with _via(_openai(create)):
        result = client.call_model("system", "user")

    assert result.text == "recovered"
    assert create.call_count == 4


def test_openai_does_not_retry_a_bad_request(monkeypatch):
    create = Mock(side_effect=_openai_status_error(openai.BadRequestError, 400))
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with _via(_openai(create)):
        with pytest.raises(openai.BadRequestError):
            client.call_model("system", "user")

    assert create.call_count == 1


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def test_unset_provider_means_anthropic_with_its_default_model():
    # The "no config change" promise: an existing .env keeps working.
    assert settings._llm_choice(None, None) == ("anthropic", "claude-sonnet-4-6")
    assert settings._llm_choice(None, "claude-opus-5") == ("anthropic", "claude-opus-5")


def test_other_providers_get_no_default_model():
    assert settings._llm_choice(" OpenAI ", None) == ("openai", None)
    assert settings._llm_choice("openai", "gpt-test") == ("openai", "gpt-test")


def test_openai_provider_builds_its_client_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "MODEL_NAME", "gpt-test")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://localhost:11434/v1")
    sdk = Mock()
    monkeypatch.setattr(client.openai, "OpenAI", sdk)

    provider = client.get_provider()

    assert isinstance(provider, client.OpenAICompatProvider)
    sdk.assert_called_once_with(
        api_key="sk-test",
        base_url="http://localhost:11434/v1",
        max_retries=0,
        timeout=client.REQUEST_TIMEOUT_SECONDS,
    )
    assert client.get_provider() is provider  # built once, then cached
    assert sdk.call_count == 1


def test_openai_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        client.get_provider()


def test_openai_requires_a_model_name(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "MODEL_NAME", None)

    with pytest.raises(RuntimeError, match="MODEL_NAME"):
        client.get_provider()


def test_unknown_provider_is_rejected_by_name(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mistral")

    with pytest.raises(RuntimeError, match="LLM_PROVIDER='mistral' is not supported"):
        client.get_provider()
