from evaluation.prompts import SYSTEM_PROMPT, build_user_prompt

TICKET = {
    "ticket_id": "TKT-42",
    "user_name": "PlayerOne",
    "user_id": "USR-99",
    "ticket_issue_category": "Request Account Unban",
    "ticket_title": "Please unban me",
    "ticket_body": "I did not cheat, my stats are just good.",
}

BAN_RECORD = {
    "user_id": "USR-99",
    "ban_reason": "Aimbot detected in ranked match",
    "detection_method": "cheat_engine_signature",
    "ban_duration": "permanent",
    "ban_date": "2026-05-01",
}


def test_build_user_prompt_includes_ticket_fields():
    prompt = build_user_prompt(TICKET, BAN_RECORD)

    for value in TICKET.values():
        assert value in prompt


def test_build_user_prompt_with_ban_record_includes_ban_fields():
    prompt = build_user_prompt(TICKET, BAN_RECORD)

    assert "Aimbot detected in ranked match" in prompt
    assert "cheat_engine_signature" in prompt
    assert "permanent" in prompt
    assert "2026-05-01" in prompt


def test_build_user_prompt_without_ban_record_says_no_ban():
    prompt = build_user_prompt(TICKET, ban_record=None)

    assert "NO BAN RECORD FOUND" in prompt


def test_system_prompt_contains_category_names():
    for category in (
        "Auto-Deny",
        "Likely Legitimate",
        "Admitted to Cheating",
        "Templated/Bot Appeal",
        "Needs Review",
    ):
        assert category in SYSTEM_PROMPT
