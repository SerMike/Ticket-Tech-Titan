"""generate_surge.py — Generate the demo banwave dataset for appeal-surge detection.

Story: a stat_anomaly (soft-signal) detection over-fired on 2026-04-10, and
the resulting appeals spike on the morning of 2026-04-11. 124 tickets land
between 08:50 and 09:48, 102 of them from stat_anomaly bans. Deterministic
(seeded), so the committed output always matches this script.

Produces data/surge_tickets.json and data/surge_bans.json in the same shape as
data/sample_tickets.json and data/sample_bans.json, so they ingest through
the normal pipeline:

    python scripts/generate_surge.py

Ticket IDs are prefixed TKT-SURGE- (users USR-SURGE-) so the demo data is easy
to identify and delete without touching the curated sample set.
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_tickets import (  # noqa: E402
    BAN_REASONS,
    BODY_TEMPLATES,
    NAME_PARTS_A,
    NAME_PARTS_B,
)

SEED = 20260411
FIRST = datetime(2026, 4, 11, 8, 50, 0)
LAST = datetime(2026, 4, 11, 9, 48, 0)

# (count, detection_method, ban_date) per slice; None means the user has no ban.
SLICES = [
    (102, "stat_anomaly", "2026-04-10"),
    (11, "cheat_engine_detection", "2026-04-09"),
    (6, None, None),
    (1, "aim_lock_detection", "2026-04-08"),
    (1, "speed_hack", "2026-04-07"),
    (1, "connection_manipulation", "2026-04-06"),
    (1, "manual_review", "2026-04-05"),
    (1, "aim_lock_detection", "2026-04-03"),
]


def generate() -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    total = sum(count for count, _, _ in SLICES)

    # First and last are pinned; the rest are distinct seeded-random seconds.
    span = int((LAST - FIRST).total_seconds())
    offsets = sorted([0, span] + rng.sample(range(1, span), total - 2))
    times = [FIRST + timedelta(seconds=o) for o in offsets]

    # Interleave the slices in time.
    assignments = [s for s in SLICES for _ in range(s[0])]
    rng.shuffle(assignments)

    tickets, bans = [], []
    banwave_seen = 0
    for i, (created, (_, method, ban_date)) in enumerate(zip(times, assignments), start=1):
        user_id = f"USR-SURGE-{i:05d}"
        if method == "stat_anomaly":
            title, body_template = BODY_TEMPLATES[1 if banwave_seen % 2 == 0 else 4]
            banwave_seen += 1
        else:
            title, body_template = rng.choice(BODY_TEMPLATES)
        body = body_template.format(
            years=rng.randint(1, 9),
            days=rng.randint(2, 14),
            spent=rng.choice([100, 250, 500, 1200]),
            cheat=rng.choice(["ESP hack", "aimbot", "wallhack trainer"]),
            mouse=rng.choice(["Logitech G502", "Razer Naga", "SteelSeries Rival"]),
            glitch=rng.choice(["wall-clip", "infinite-ammo", "rank-reset"]),
            date=(FIRST - timedelta(days=rng.randint(1, 10))).date().isoformat(),
        )
        tickets.append({
            "ticket_id": f"TKT-SURGE-{i:05d}",
            "user_name": rng.choice(NAME_PARTS_A) + rng.choice(NAME_PARTS_B)
            + str(rng.randint(1, 99)),
            "user_id": user_id,
            "ticket_issue_category": "Request Account Unban",
            "ticket_title": title,
            "ticket_body": body,
            "status": "open",
            "created_at": created.isoformat(timespec="seconds"),
        })
        if method is not None:
            bans.append({
                "user_id": user_id,
                "ban_reason": BAN_REASONS[method],
                "detection_method": method,
                "ban_duration": rng.choice(["permanent", "30 days", "90 days"]),
                "ban_date": ban_date,
            })
    return tickets, bans


def main() -> int:
    tickets, bans = generate()

    tickets_path = ROOT / "data" / "surge_tickets.json"
    bans_path = ROOT / "data" / "surge_bans.json"
    tickets_path.write_text(json.dumps({"tickets": tickets}, indent=1), encoding="utf-8")
    bans_path.write_text(json.dumps({"bans": bans}, indent=1), encoding="utf-8")

    print(f"Wrote {len(tickets)} tickets to {tickets_path}")
    print(f"Wrote {len(bans)} bans to {bans_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
