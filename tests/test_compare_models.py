import json

import pytest

from evaluation import evaluator
from evaluation.client import ModelResponse
from evaluation.evaluator import EvaluationError
from scripts import compare_models as cm


EVALUATION = {
    "ai_summary": "The player denies cheating.",
    "ai_category": "Needs Review",
    "admitted_cheating": False,
    "admitted_exploit": False,
    "confidence_score": 0.6,
    "ai_reasoning": "Worth a human look.",
}

TICKET = {
    "ticket_id": "TKT-1",
    "user_name": "PlayerOne",
    "user_id": "USR-1",
    "ticket_issue_category": "Request Account Unban",
    "ticket_title": "Please review my ban",
    "ticket_body": "I think this was a false positive.",
}

CONFIRMED_BAN = {
    "user_id": "USR-1",
    "ban_reason": "Cheat software detected",
    "detection_method": "cheat_engine_detection",
    "ban_duration": "permanent",
    "ban_date": "2026-03-18",
}


def _install(monkeypatch, response=None, error=None):
    """Swap call_model for a recorder around a fake, as main() does."""
    def fake(**kwargs):
        if error is not None:
            raise error
        return response

    recorder = cm.UsageRecorder(fake)
    monkeypatch.setattr(evaluator, "call_model", recorder)
    return recorder


def _response(text, output_tokens=200):
    return ModelResponse(text=text, model_name="claude-haiku-5-5",
                         input_tokens=2900, output_tokens=output_tokens)


def _call(model, ticket_id, category="Auto-Deny", run=1, cheat=False, **extra):
    fields = dict(model=model, ticket_id=ticket_id, run=run, seconds=1.0,
                  input_tokens=2000, output_tokens=200, category=category,
                  final_category=category, admitted_cheating=cheat,
                  admitted_exploit=False, confidence=0.9)
    return cm.Call(**(fields | extra))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def test_parse_spec_uses_the_default_budget_without_one():
    assert cm.parse_spec("claude-haiku-5-5", 1024) == cm.ModelSpec("claude-haiku-5-5", 1024)


def test_parse_spec_reads_a_budget_after_the_last_at_sign():
    # Ollama model names contain colons, so @ is the separator.
    assert cm.parse_spec("llama3:8b@4000", 1024) == cm.ModelSpec("llama3:8b", 4000)
    assert cm.parse_spec("claude-haiku-5-5@8000", 1024).label == "claude-haiku-5-5@8000"


@pytest.mark.parametrize("text", ["claude-haiku-5-5@0", "claude-haiku-5-5@lots", "@4000"])
def test_parse_spec_rejects_bad_specs(text):
    with pytest.raises(ValueError):
        cm.parse_spec(text, 1024)


def test_load_samples_matches_the_pipeline_row_shape():
    pairs = cm.load_samples(cm.SAMPLE_TICKETS, cm.SAMPLE_BANS)

    ids = [t["ticket_id"] for t, _ in pairs]
    assert ids == sorted(ids)
    ticket, ban = pairs[0]
    assert set(ticket) == set(TICKET)
    assert set(ban) == set(CONFIRMED_BAN)
    assert isinstance(ban["ban_date"], str)
    assert ban["user_id"] == ticket["user_id"]


def test_model_decided_only_when_auto_deny_cannot_override():
    assert cm.model_decided(None)
    assert cm.model_decided(CONFIRMED_BAN | {"detection_method": "stat_anomaly"})
    assert not cm.model_decided(CONFIRMED_BAN)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc, tokens, expected", [
    (RuntimeError("Anthropic API returned no text content. Stop reason: max_tokens"),
     None, cm.NO_ANSWER),
    (RuntimeError("OpenAI-compatible API returned no text content. Finish reason: length"),
     None, cm.NO_ANSWER),
    (RuntimeError("Anthropic API returned no text content. Stop reason: refusal"),
     None, cm.REFUSED),
    (EvaluationError("Model response is not valid JSON."), 1024, cm.CUT_OFF),
    (EvaluationError("Model response is not valid JSON."), 300, cm.INVALID),
    (EvaluationError("Missing required fields"), None, cm.INVALID),
    (ValueError("boom"), None, "error: ValueError"),
])
def test_classify_failure(exc, tokens, expected):
    assert cm.classify_failure(exc, tokens, budget=1024) == expected


def test_run_one_keeps_the_models_own_category_and_the_final_one(monkeypatch):
    recorder = _install(monkeypatch, _response(json.dumps(EVALUATION)))

    call = cm.run_one(cm.ModelSpec("claude-haiku-5-5", 8000), TICKET, CONFIRMED_BAN, 1,
                      recorder)

    assert call.ok
    assert call.category == "Needs Review"
    assert call.final_category == "Auto-Deny"  # the confirmed detection overrides
    assert (call.input_tokens, call.output_tokens) == (2900, 200)


def test_run_one_counts_the_tokens_of_a_reply_cut_off_at_the_budget(monkeypatch):
    truncated = json.dumps(EVALUATION)[:40]
    recorder = _install(monkeypatch, _response(truncated, output_tokens=1024))

    call = cm.run_one(cm.ModelSpec("claude-haiku-5-5", 1024), TICKET, CONFIRMED_BAN, 1,
                      recorder)

    assert call.failure == cm.CUT_OFF
    assert call.output_tokens == 1024
    assert call.category is None


def test_run_one_does_not_reuse_the_previous_calls_tokens(monkeypatch):
    recorder = _install(monkeypatch, error=RuntimeError("Stop reason: max_tokens"))
    recorder.last = _response("left over from the previous ticket")

    call = cm.run_one(cm.ModelSpec("claude-haiku-5-5", 1024), TICKET, None, 1, recorder)

    assert call.failure == cm.NO_ANSWER
    assert call.input_tokens is None and call.output_tokens is None


def test_run_one_aborts_on_errors_every_call_would_repeat(monkeypatch):
    error = RuntimeError("invalid x-api-key")
    error.status_code = 401
    recorder = _install(monkeypatch, error=error)

    with pytest.raises(cm.AbortRun, match="claude-haiku-5-5"):
        cm.run_one(cm.ModelSpec("claude-haiku-5-5", 1024), TICKET, None, 1, recorder)


def test_pick_recheck_puts_model_decided_then_category_then_flag_differences_first():
    base, other = "sonnet@1024", "haiku@8000"
    calls = [
        _call(base, "T1"), _call(other, "T1", cheat=True),                  # flag only
        _call(base, "T2"), _call(other, "T2", category="Needs Review"),     # category
        _call(base, "T3"), _call(other, "T3"),                              # same
        _call(base, "T4"), _call(other, "T4", category=None, failure="refused"),
        _call(base, "T5", category="Needs Review"), _call(other, "T5", category="Needs Review"),
    ]

    assert cm.pick_recheck(calls, base, decided_ids={"T5"}, cap=10) == ["T5", "T2", "T1"]
    assert cm.pick_recheck(calls, base, decided_ids={"T5"}, cap=2) == ["T5", "T2"]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_summarize_compares_against_the_baseline_and_scores_stability():
    specs = [cm.ModelSpec("claude-sonnet-4-6", 1024), cm.ModelSpec("claude-haiku-5-5", 8000)]
    base, other = (s.label for s in specs)
    calls = [
        _call(base, "T1"), _call(other, "T1", category="Admitted to Cheating", cheat=True),
        _call(base, "T2", category="Needs Review"), _call(other, "T2", category="Needs Review"),
        # Re-check runs on T1: the baseline holds steady, the other model flips.
        _call(base, "T1", run=2), _call(other, "T1", run=2),
        # A failed call with no usage stays unpriced rather than counting as $0.
        _call(other, "T3", category=None, input_tokens=None, output_tokens=None,
              failure=cm.NO_ANSWER),
    ]

    summary = cm.summarize(calls, specs, decided_ids={"T2"}, recheck_ids=["T1"])

    versus = summary["versus_baseline"][other]
    assert versus["compared"] == 2
    assert versus["same_category"] == 1
    assert versus["same_admitted_cheating"] == 1
    assert versus["disagreements"] == ["T1"]
    assert (versus["model_decided_compared"], versus["model_decided_same_final"]) == (1, 1)
    assert versus["confusion"]["Auto-Deny"] == {"Admitted to Cheating": 1}

    stability = summary["stability"]
    assert (stability[base]["rechecked"], stability[base]["stable"]) == (1, 1)
    assert (stability[other]["rechecked"], stability[other]["stable"]) == (1, 0)
    assert stability[other]["tallies"]["T1"] == "Admit(cheat) x1, Deny x1"

    haiku = summary["models"][other]
    assert haiku["answered"] == 2 and haiku["failures"] == {cm.NO_ANSWER: 1}
    assert haiku["unpriced_calls"] == 1
    # Three priced Haiku calls at 2,000 in / 200 out: $0.10 and $0.50 per million.
    assert haiku["spend"] == pytest.approx(3 * (2000 * 0.10 + 200 * 0.50) / 1_000_000)
