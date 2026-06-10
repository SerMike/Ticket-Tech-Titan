"""generate_tickets.py — Generate synthetic tickets + ban records for performance testing.

Produces JSON files in the same shape as data/sample_tickets.json and
data/sample_bans.json so they ingest through the normal pipeline:

    python scripts/generate_tickets.py --count 500 --output data/perf_tickets.json

Ticket IDs are prefixed TKT-PERF- (users USR-PERF-) so performance data is
easy to identify and delete without touching the curated sample set.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.auto_deny import CONFIRMED_DETECTION_METHODS  # noqa: E402

# The four confirmed (auto-deny) methods plus the two soft signals.
DETECTION_METHODS = sorted(CONFIRMED_DETECTION_METHODS) + [
    "manual_review",
    "stat_anomaly",
]

BAN_REASONS = {
    "cheat_engine_detection": "Cheat engine signature detected during live match",
    "aim_lock_detection": "Server-side aim-lock detection triggered repeatedly",
    "speed_hack": "Movement speed exceeded engine limits in ranked play",
    "connection_manipulation": "Malicious packet manipulation detected",
    "manual_review": "Banned after manual review of player reports",
    "stat_anomaly": "Statistical anomaly in accuracy and reaction times",
}

# Five appeal archetypes varied from data/sample_tickets.json: generic denial,
# specific/plausible, cheating admission, exploit admission, templated/bot.
BODY_TEMPLATES = [
    (
        "Appeal - please review",
        "Unban please. I didn't cheat. First offense. Been playing {years} years. "
        "Check my stats. Thanks.",
    ),
    (
        "Wrongful ban after hardware upgrade",
        "I just built a brand new PC last week — new motherboard, new CPU, new RAM. "
        "I have receipts and timestamped photos of the build, plus a full VOD of the "
        "session I was banned in. I think the anti-cheat flagged my fresh Windows "
        "install. I can provide my process list and crash dumps from {date}.",
    ),
    (
        "I want to come clean",
        "I'm not going to lie to you — I used an {cheat} for about {days} days. It was "
        "the first time I ever tried anything like it and I regret it. I've spent "
        "${spent} on this game and I'm asking for one more chance.",
    ),
    (
        "Banned for using a macro?",
        "I set up a rapid-fire macro on my {mouse} mouse using the vendor software. "
        "I honestly didn't think peripheral software counted as cheating — everyone "
        "in my clan uses them. I also abused the {glitch} glitch a couple of times "
        "because it was funny, but I never installed any hacks.",
    ),
    (
        "Unfair ban — loyal player",
        "Dear support team, I believe my ban was wrongful. I am a loyal player and "
        "have never used cheats of any kind. I have {years} years of playtime and "
        "have spent ${spent} on the game. Please review my account and restore my "
        "access. Thank you for your understanding.",
    ),
]

NAME_PARTS_A = ["Shadow", "Sneaky", "Turbo", "Quick", "Iron", "Neon", "Frost", "Pixel"]
NAME_PARTS_B = ["Wolf", "Pete", "Sniper", "Ninja", "Falcon", "Ghost", "Viper", "Rogue"]


def generate(count: int) -> tuple[list[dict], list[dict]]:
    tickets, bans = [], []
    now = datetime(2026, 6, 9, 12, 0, 0)
    for i in range(1, count + 1):
        user_id = f"USR-PERF-{i:05d}"
        title, body_template = BODY_TEMPLATES[i % len(BODY_TEMPLATES)]
        body = body_template.format(
            years=random.randint(1, 9),
            days=random.randint(2, 14),
            spent=random.choice([100, 250, 500, 1200]),
            cheat=random.choice(["ESP hack", "aimbot", "wallhack trainer"]),
            mouse=random.choice(["Logitech G502", "Razer Naga", "SteelSeries Rival"]),
            glitch=random.choice(["wall-clip", "infinite-ammo", "rank-reset"]),
            date=(now - timedelta(days=random.randint(1, 10))).date().isoformat(),
        )
        created = now - timedelta(
            days=random.randint(0, 59),
            seconds=random.randint(0, 86399),
        )
        tickets.append({
            "ticket_id": f"TKT-PERF-{i:05d}",
            "user_name": random.choice(NAME_PARTS_A) + random.choice(NAME_PARTS_B)
            + str(random.randint(1, 99)),
            "user_id": user_id,
            "ticket_issue_category": "Request Account Unban",
            "ticket_title": title,
            "ticket_body": body,
            "status": "open",
            "created_at": created.isoformat(timespec="seconds"),
        })

        method = DETECTION_METHODS[i % len(DETECTION_METHODS)]
        bans.append({
            "user_id": user_id,
            "ban_reason": BAN_REASONS[method],
            "detection_method": method,
            "ban_duration": random.choice(["permanent", "30 days", "90 days"]),
            "ban_date": (created - timedelta(days=random.randint(1, 14))).date().isoformat(),
        })
    return tickets, bans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--output", default="data/perf_tickets.json",
                        help="Tickets output path (bans go to the sibling perf_bans.json).")
    args = parser.parse_args()

    tickets, bans = generate(args.count)

    tickets_path = Path(args.output)
    bans_path = tickets_path.parent / "perf_bans.json"
    tickets_path.write_text(json.dumps({"tickets": tickets}, indent=1), encoding="utf-8")
    bans_path.write_text(json.dumps({"bans": bans}, indent=1), encoding="utf-8")

    print(f"Wrote {len(tickets)} tickets to {tickets_path}")
    print(f"Wrote {len(bans)} bans to {bans_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
