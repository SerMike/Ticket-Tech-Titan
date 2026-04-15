# Prompt Examples — Ticket Evaluation

Reference set of worked (ticket + ban record + expected JSON output) triples.
Currently used as **documentation only** — the model operates in zero-shot mode
against `SYSTEM_PROMPT`. If outputs drift, wire these into `evaluator.py` as
few-shot `user`/`assistant` turn pairs before sending the real ticket.

The three core examples cover the three most common buckets. Example 4
(Likely Legitimate) is held in reserve for the rare ~1% case.

---

## Example 1 — Auto-Deny

**TICKET:**
```
ticket_id: TKT-10042
user_name: ShadowBlade99
user_id: USR-48291
ticket_issue_category: Request Account Unban
ticket_title: Wrongful ban - never cheated
ticket_body:
"""
I was banned last week but I have never used any cheats. I think my account
may have been compromised. I've been playing this game for 3 years and have
spent over $500. Please review my case and unban my account. This is really
unfair.
"""
```

**BAN RECORD:**
```
user_id: USR-48291
ban_reason: Use of unauthorized third-party software
detection_method: cheat_engine_signature
ban_duration: permanent
ban_date: 2026-04-07
```

**EXPECTED JSON OUTPUT:**
```json
{
  "ai_summary": "Player denies cheating and suggests their account was compromised. Ban record shows a confirmed cheat-engine signature detection on 2026-04-07.",
  "ai_category": "Auto-Deny",
  "admitted_cheating": false,
  "admitted_exploit": false,
  "confidence_score": 0.97,
  "ai_reasoning": "The ban was triggered by a cheat_engine_signature, which is a high-confidence technical detection. The player offers no specific evidence of account compromise (no date, no platform, no security details) and leans on tenure and money spent rather than facts. Per the auto-deny rule, confirmed cheat-software signatures override the player's denial."
}
```

---

## Example 2 — Admitted to Cheating

**TICKET:**
```
ticket_id: TKT-10058
user_name: NightOwl_2k
user_id: USR-51177
ticket_issue_category: Request Account Unban
ticket_title: I'm sorry, please give me another chance
ticket_body:
"""
Look I'll be honest, I used a recoil script for like a week because my friends
were beating me and I got frustrated. I know it was wrong and I deleted it.
This is my main account and I've put hundreds of hours in. I promise I won't
do it again. Can you please reduce the ban or give me a second chance?
"""
```

**BAN RECORD:**
```
user_id: USR-51177
ban_reason: Use of macro/script for gameplay advantage
detection_method: behavioral_recoil_anomaly
ban_duration: 30 days
ban_date: 2026-04-09
```

**EXPECTED JSON OUTPUT:**
```json
{
  "ai_summary": "Player explicitly admits to using a recoil script for about a week and asks for leniency. Ban record corroborates with a behavioral recoil anomaly detection.",
  "ai_category": "Admitted to Cheating",
  "admitted_cheating": true,
  "admitted_exploit": false,
  "confidence_score": 0.98,
  "ai_reasoning": "The player directly admits to using a recoil script — a third-party tool that automates input for gameplay advantage, which qualifies as cheating under standard industry policy. The ban record's behavioral_recoil_anomaly detection is consistent with the admission. Category is Admitted to Cheating rather than Auto-Deny because the detection method is behavioral rather than a confirmed cheat-software signature, but the player's own admission settles the question."
}
```

---

## Example 3 — Templated / Bot Appeal

**TICKET:**
```
ticket_id: TKT-10073
user_name: PlayerX_8842
user_id: USR-60214
ticket_issue_category: Request Account Unban
ticket_title: Please unban my account
ticket_body:
"""
Dear Support Team,

I am writing to respectfully request the review of my account ban. I have
always been a loyal player and have followed all rules. I believe this ban
was issued in error and I would greatly appreciate your prompt attention to
this matter. Thank you for your time and consideration.

Best regards,
A loyal player
"""
```

**BAN RECORD:**
```
user_id: USR-60214
ban_reason: Use of unauthorized third-party software
detection_method: cheat_software_signature
ban_duration: permanent
ban_date: 2026-04-10
```

**EXPECTED JSON OUTPUT:**
```json
{
  "ai_summary": "Generic, formally-worded appeal with no specifics about the player, the game, or the alleged ban reason. Ban record shows a confirmed cheat-software signature.",
  "ai_category": "Auto-Deny",
  "admitted_cheating": false,
  "admitted_exploit": false,
  "confidence_score": 0.95,
  "ai_reasoning": "The ticket reads as a copy-paste template — overly formal closing, no reference to the actual ban reason, no personal details, no specifics about gameplay or account history. Although the templated style alone would suggest the Templated/Bot Appeal bucket, the ban record shows a confirmed cheat_software_signature detection, which triggers the auto-deny rule. The auto-deny override takes precedence; flagging the templated style in reasoning for analytics."
}
```

> **Note for the model:** When two buckets could apply, the auto-deny rule wins.
> We still want the templated nature called out in `ai_reasoning` so analysts
> and data scientists can spot bot patterns.

---

## Example 4 — Likely Legitimate (Stretch / Reserve)

**TICKET:**
```
ticket_id: TKT-10091
user_name: CasualDad42
user_id: USR-71005
ticket_issue_category: Request Account Unban
ticket_title: Banned mid-match after PC crash
ticket_body:
"""
Hi, my game crashed last Tuesday around 8:30pm EST during a ranked match
on the Verdant Pass map. When I logged back in 10 minutes later my account
was banned for "connection manipulation." I checked my router logs and the
crash was a Windows blue screen (driver_irql_not_less_or_equal). I've never
used a VPN or any kind of network tool. I have the crash dump file if it
helps. I've been playing since launch and have never been flagged before.
"""
```

**BAN RECORD:**
```
NO BAN RECORD FOUND for this user_id.
```

**EXPECTED JSON OUTPUT:**
```json
{
  "ai_summary": "Player reports a Windows BSOD mid-match followed by an unexpected ban for connection manipulation. No internal ban record exists for this user_id.",
  "ai_category": "Likely Legitimate",
  "admitted_cheating": false,
  "admitted_exploit": false,
  "confidence_score": 0.72,
  "ai_reasoning": "The appeal is unusually specific — exact time, map, error code, and offer of a crash dump — which is uncharacteristic of a fabricated story. More importantly, no ban record exists in our internal system for this user_id, which is a strong signal the ban may not have been properly applied or has been reversed already. Recommend priority human review to either confirm there was no ban or surface the missing record."
}
```

---

## Iteration Notes

When an output looks wrong, capture the (ticket + ban + bad output) triple
in `evaluation/regression_cases.md` so prompt edits can be re-tested against it.
Common failure modes to watch:

- False auto-denies on soft signals (stat anomalies, behavioral-only flags)
- Over-eager `admitted_cheating = true` on ambiguous hedging language
- Templated appeals landing in `Needs Review` instead of `Templated/Bot Appeal`
- Confidence pinned at 0.95 across the board (poor calibration)
- Invented ban-record details that weren't in the input
