from evaluation.auto_deny import enforce_auto_deny


def test_enforce_auto_deny_overrides_confirmed_detection():
    result = {
        "ticket_id": "TKT-1",
        "ai_category": "Needs Review",
        "ai_reasoning": "Initial reasoning.",
    }
    ban = {"detection_method": "cheat_engine_detection"}

    updated = enforce_auto_deny(result, ban)

    assert updated["ai_category"] == "Auto-Deny"
    assert "AUTO-DENY OVERRIDE" in updated["ai_reasoning"]


def test_enforce_auto_deny_preserves_admitted_to_cheating():
    result = {
        "ticket_id": "TKT-1",
        "ai_category": "Admitted to Cheating",
        "ai_reasoning": "The player admitted it.",
    }
    ban = {"detection_method": "cheat_engine_detection"}

    updated = enforce_auto_deny(result, ban)

    assert updated["ai_category"] == "Admitted to Cheating"
    assert "AUTO-DENY OVERRIDE" not in updated["ai_reasoning"]


def test_enforce_auto_deny_ignores_missing_or_soft_ban_record():
    result = {"ai_category": "Needs Review", "ai_reasoning": "Initial."}

    assert enforce_auto_deny(result.copy(), None)["ai_category"] == "Needs Review"
    assert enforce_auto_deny(
        result.copy(), {"detection_method": "manual_review"}
    )["ai_category"] == "Needs Review"
