import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from config import settings
from dashboard import surge


def test_positive_int_defaults_when_unset_or_empty():
    assert settings._positive_int("SURGE_THRESHOLD", None, 100) == 100
    assert settings._positive_int("SURGE_THRESHOLD", "", 100) == 100


def test_positive_int_parses_value():
    assert settings._positive_int("SURGE_WINDOW_MINUTES", "30", 60) == 30


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "1.5"])
def test_positive_int_rejects_bad_values_naming_the_variable(raw):
    with pytest.raises(RuntimeError, match="SURGE_THRESHOLD"):
        settings._positive_int("SURGE_THRESHOLD", raw, 100)


def test_surge_defaults():
    # Holds while .env leaves both unset, as .env.example does.
    assert settings.SURGE_THRESHOLD == 100
    assert settings.SURGE_WINDOW_MINUTES == 60


AS_OF = datetime(2026, 4, 11, 9, 48)
D09 = date(2026, 4, 9)
D10 = date(2026, 4, 10)


def r(minutes_before, ban_date=None, method=None):
    return {
        "created_at": AS_OF - timedelta(minutes=minutes_before),
        "ban_date": ban_date,
        "detection_method": method,
    }


def test_no_tickets():
    out = surge.detect([], None, 100, 60)
    assert out == {"active": False, "as_of": None, "window_start": None,
                   "window_minutes": 60, "threshold": 100, "count": 0,
                   "top_cause": None, "causes": []}


def test_below_threshold_reports_count_but_no_causes():
    out = surge.detect([r(1, D10, "stat_anomaly")] * 2, AS_OF, 3, 60)
    assert (out["active"], out["count"], out["top_cause"], out["causes"]) == (False, 2, None, [])
    assert out["window_start"] == AS_OF - timedelta(minutes=60)


def test_exactly_at_threshold_is_active():
    assert surge.detect([r(1, D10, "stat_anomaly")] * 3, AS_OF, 3, 60)["active"] is True


def test_window_is_half_open():
    rows = [r(60, D10, "stat_anomaly"), r(0, D10, "stat_anomaly")]  # boundary out, as_of in
    assert surge.detect(rows, AS_OF, 1, 60)["count"] == 1


def test_rows_outside_window_are_ignored():
    rows = [r(5, D10, "stat_anomaly"), r(500, D10, "stat_anomaly"), r(-5, D10, "stat_anomaly")]
    assert surge.detect(rows, AS_OF, 1, 60)["count"] == 1


def test_groups_by_ban_cluster_with_share():
    rows = [r(1, D10, "stat_anomaly")] * 3 + [r(2, D09, "cheat_engine_detection")]
    out = surge.detect(rows, AS_OF, 4, 60)
    assert out["top_cause"] == {"ban_date": D10, "detection_method": "stat_anomaly", "count": 3, "share": 0.75}
    assert out["causes"][1]["share"] == 0.25


def test_tie_goes_to_more_recent_ban_date_and_null_is_oldest():
    rows = [r(1, D09, "a"), r(1, D10, "b"), r(1)]
    out = surge.detect(rows, AS_OF, 3, 60)
    assert [c["detection_method"] for c in out["causes"]] == ["b", "a", surge.NO_BAN_LABEL]


def test_full_tie_breaks_alphabetically():
    rows = [r(1, D10, "zeta"), r(1, D10, "alpha")]
    assert surge.detect(rows, AS_OF, 2, 60)["causes"][0]["detection_method"] == "alpha"


def test_no_ban_bucket():
    out = surge.detect([r(1)] * 2, AS_OF, 2, 60)
    assert out["top_cause"] == {"ban_date": None, "detection_method": "(no ban record)", "count": 2, "share": 1.0}


def test_top_three_only():
    rows = [r(1, D10, m) for m in "abcd"]
    assert len(surge.detect(rows, AS_OF, 4, 60)["causes"]) == 3


# Review Focus 1-3
def test_later_quiet_ticket_moves_the_clock_past_the_surge():
    rows = [r(0, D10, "stat_anomaly")] * 5
    later = AS_OF + timedelta(days=60)
    assert surge.detect(rows + [{"created_at": later, "ban_date": None, "detection_method": None}],
                        later, 5, 60)["active"] is False


def test_repeat_appeals_from_one_player_each_count():
    assert surge.detect([r(1, D10, "stat_anomaly"), r(2, D10, "stat_anomaly")], AS_OF, 2, 60)["active"] is True


def test_all_tickets_at_the_as_of_second_count():
    assert surge.detect([r(0, D10, "x")] * 4, AS_OF, 4, 60)["count"] == 4


DATA = Path(__file__).resolve().parent.parent / "data"


def _load_generate_surge():
    path = DATA.parent / "scripts" / "generate_surge.py"
    spec = importlib.util.spec_from_file_location("generate_surge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _demo_rows():
    tickets = json.loads((DATA / "surge_tickets.json").read_text())["tickets"]
    bans = {b["user_id"]: b for b in json.loads((DATA / "surge_bans.json").read_text())["bans"]}
    rows = []
    for t in tickets:
        b = bans.get(t["user_id"])
        rows.append({"created_at": datetime.fromisoformat(t["created_at"]),
                     "ban_date": date.fromisoformat(b["ban_date"]) if b else None,
                     "detection_method": b["detection_method"] if b else None})
    return rows


def test_demo_dataset_triggers_the_stat_anomaly_surge():
    rows = _demo_rows()
    as_of = max(r["created_at"] for r in rows)
    out = surge.detect(rows, as_of, settings.SURGE_THRESHOLD, settings.SURGE_WINDOW_MINUTES)
    assert out["active"] is True
    assert (out["top_cause"]["detection_method"], out["top_cause"]["ban_date"]) == ("stat_anomaly", date(2026, 4, 10))


def test_demo_dataset_is_newer_than_the_base_sample():
    base = json.loads((DATA / "sample_tickets.json").read_text())["tickets"]
    surge_t = json.loads((DATA / "surge_tickets.json").read_text())["tickets"]
    assert min(t["created_at"] for t in surge_t) > max(t["created_at"] for t in base)


def test_committed_demo_files_match_the_generator():
    gen = _load_generate_surge()
    tickets, bans = gen.generate()
    assert {"tickets": tickets} == json.loads((DATA / "surge_tickets.json").read_text())
    assert {"bans": bans} == json.loads((DATA / "surge_bans.json").read_text())
