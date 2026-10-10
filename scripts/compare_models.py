"""compare_models.py — Side-by-side check of models on the sample tickets.

Runs every sample ticket (data/sample_tickets.json, joined to its ban record
in data/sample_bans.json the way the pipeline joins them) through the same
evaluate_ticket() + enforce_auto_deny() path the pipeline uses, once per
model, and reports how often each model agrees with the first one (the
baseline), what it costs, how fast it answers, and how it fails.

Nothing touches the database. Results go to stdout and to a JSON file
(model-comparison-<timestamp>.json, gitignored) that holds every call.

This calls the live API and costs money. With the default models a full run
costs about $0.60, the re-check pass adds at most about $0.40, and the whole
thing takes 15-25 minutes.

Usage:
    python scripts/compare_models.py
    python scripts/compare_models.py --limit 5        # quick trial run
    python scripts/compare_models.py --models claude-sonnet-4-6 claude-haiku-5-5@8000

Each model is NAME or NAME@BUDGET, where BUDGET is its reply budget in tokens
(LLM_MAX_TOKENS when omitted). By default the baseline is your MODEL_NAME and
it is compared with claude-haiku-5-5 at two budgets: Haiku 5.5 thinks before
it answers, and its thinking counts against the budget.

Reading the results
-------------------
Most sample tickets carry a confirmed detection, where enforce_auto_deny()
decides the final category whatever the model says. So the report compares
each model's own category (before that override) and its admission flags,
and counts the model-decided tickets separately: there the model's answer is
the final one.

Models answer differently from run to run, so a single disagreement can be
noise. The re-check pass runs every model again (--recheck times) on the
tickets that matter most, the model-decided ones and any where a model
disagreed with the baseline, up to RECHECK_CAP tickets.
"""

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from dashboard.cost import cost_usd  # noqa: E402
from evaluation import evaluator  # noqa: E402
from evaluation.auto_deny import CONFIRMED_DETECTION_METHODS, enforce_auto_deny  # noqa: E402
from evaluation.client import get_provider  # noqa: E402

SAMPLE_TICKETS = PROJECT_ROOT / "data" / "sample_tickets.json"
SAMPLE_BANS = PROJECT_ROOT / "data" / "sample_bans.json"

# Compared with the baseline (MODEL_NAME) when --models isn't given.
DEFAULT_CHALLENGERS = ["claude-haiku-5-5", "claude-haiku-5-5@8000"]

# Most tickets the re-check pass runs again. Bounds its cost: with the
# default models, about 1.2 cents per ticket per re-check round.
RECHECK_CAP = 15

# Failure classes, as the report groups them.
NO_ANSWER = "budget spent before answering"
CUT_OFF = "budget ran out mid-answer"
REFUSED = "refused"
INVALID = "invalid answer"

# Short names keep the report's tables narrow.
SHORT = {
    "Auto-Deny": "Deny",
    "Admitted to Cheating": "Admit",
    "Likely Legitimate": "Legit",
    "Templated/Bot Appeal": "Bot",
    "Needs Review": "Review",
}


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelSpec:
    """One model at one reply budget: one column of the comparison."""

    model: str
    budget: int

    @property
    def label(self) -> str:
        return f"{self.model}@{self.budget}"


def parse_spec(text: str, default_budget: int) -> ModelSpec:
    """Parse NAME or NAME@BUDGET. Raises ValueError naming the problem."""
    name, sep, raw_budget = text.rpartition("@")
    if not sep:
        name, raw_budget = text, ""
    name = name.strip()
    if not name:
        raise ValueError(f"{text!r} has no model name")
    if not raw_budget:
        return ModelSpec(name, default_budget)
    try:
        budget = int(raw_budget)
    except ValueError:
        budget = 0
    if budget < 1:
        raise ValueError(
            f"{text!r}: the budget after @ must be a positive whole number of tokens"
        )
    return ModelSpec(name, budget)


def load_samples(tickets_path: Path, bans_path: Path) -> list[tuple[dict, dict | None]]:
    """Return (ticket, ban_record_or_None) pairs shaped like the pipeline's
    (see run_pipeline._split_row), ordered by ticket_id as it orders them."""
    tickets = json.loads(tickets_path.read_text(encoding="utf-8"))["tickets"]
    bans = json.loads(bans_path.read_text(encoding="utf-8"))["bans"]
    ban_by_user = {b["user_id"]: b for b in bans}  # one ban per user in the samples

    pairs = []
    for t in sorted(tickets, key=lambda t: t["ticket_id"]):
        ticket = {
            "ticket_id": t["ticket_id"],
            "user_name": t["user_name"],
            "user_id": t["user_id"],
            "ticket_issue_category": t["ticket_issue_category"],
            "ticket_title": t["ticket_title"],
            "ticket_body": t["ticket_body"],
        }
        b = ban_by_user.get(t["user_id"])
        ban = None if b is None else {
            "user_id": b["user_id"],
            "ban_reason": b["ban_reason"],
            "detection_method": b["detection_method"],
            "ban_duration": b["ban_duration"],
            "ban_date": str(b["ban_date"]),
        }
        pairs.append((ticket, ban))
    return pairs


def model_decided(ban: dict | None) -> bool:
    """True when enforce_auto_deny() can't override the model's category."""
    return ban is None or ban.get("detection_method") not in CONFIRMED_DETECTION_METHODS


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@dataclass
class Call:
    """One evaluation of one ticket by one model, successful or not."""

    model: str          # ModelSpec.label
    ticket_id: str
    run: int            # 1 = main pass, 2+ = re-check rounds
    seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    category: str | None = None        # the model's own answer
    final_category: str | None = None  # after enforce_auto_deny()
    admitted_cheating: bool | None = None
    admitted_exploit: bool | None = None
    confidence: float | None = None
    summary: str | None = None
    reasoning: str | None = None
    failure: str | None = None         # see classify_failure()
    error: str | None = None           # the exception's text, trimmed

    @property
    def ok(self) -> bool:
        return self.failure is None

    def answer(self) -> tuple:
        """What two runs must share to count as the same answer."""
        return (self.category, self.admitted_cheating, self.admitted_exploit)


class UsageRecorder:
    """Stands in for evaluation.evaluator.call_model and keeps the last
    response, so a call's tokens are counted even when the evaluation fails
    after the API answered: a reply cut off mid-JSON is still billed."""

    def __init__(self, call):
        self._call = call
        self.last = None

    def __call__(self, *args, **kwargs):
        self.last = None
        self.last = self._call(*args, **kwargs)
        return self.last


class AbortRun(Exception):
    """A failure every remaining call would repeat, such as a bad key."""


def classify_failure(exc: Exception, output_tokens: int | None, budget: int) -> str:
    """Name why a call produced no valid evaluation.

    output_tokens is what the API billed for the reply, when there was one:
    a reply that filled the whole budget was cut off, not malformed. A
    refusal that came back with some text classifies as an invalid answer;
    the error text in the results file shows which it was.
    """
    text = str(exc)
    if "Stop reason: max_tokens" in text or "Finish reason: length" in text:
        return NO_ANSWER
    if "Stop reason: refusal" in text:
        return REFUSED
    if isinstance(exc, evaluator.EvaluationError):
        if output_tokens is not None and output_tokens >= budget:
            return CUT_OFF
        return INVALID
    return f"error: {type(exc).__name__}"


def run_one(spec: ModelSpec, ticket: dict, ban: dict | None, run: int,
            recorder: UsageRecorder) -> Call:
    """Evaluate one ticket the way the pipeline does, minus the write."""
    recorder.last = None  # so a failure before the API call can't inherit tokens
    started = time.monotonic()
    try:
        result = evaluator.evaluate_ticket(ticket, ban)
    except Exception as exc:  # noqa: BLE001 — a failure is a result here
        if getattr(exc, "status_code", None) in (401, 403, 404):
            raise AbortRun(f"{spec.model}: {type(exc).__name__}: {exc}") from exc
        usage = recorder.last
        return Call(
            model=spec.label,
            ticket_id=ticket["ticket_id"],
            run=run,
            seconds=time.monotonic() - started,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            failure=classify_failure(exc, usage.output_tokens if usage else None, spec.budget),
            error=str(exc)[:500],
        )

    seconds = time.monotonic() - started
    category = result["ai_category"]
    final = enforce_auto_deny(dict(result), ban)["ai_category"]
    return Call(
        model=spec.label,
        ticket_id=ticket["ticket_id"],
        run=run,
        seconds=seconds,
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        category=category,
        final_category=final,
        admitted_cheating=result["admitted_cheating"],
        admitted_exploit=result["admitted_exploit"],
        confidence=result["confidence_score"],
        summary=result["ai_summary"],
        reasoning=result["ai_reasoning"],
    )


def pick_recheck(calls: list[Call], baseline: str, decided_ids: set[str],
                 cap: int) -> list[str]:
    """Choose the tickets worth running again, most informative first: the
    model-decided ones, then any where a model's category differs from the
    baseline's, then any where only an admission flag differs."""
    base = {c.ticket_id: c for c in calls if c.run == 1 and c.model == baseline and c.ok}
    category_diff, flag_diff = set(), set()
    for c in calls:
        b = base.get(c.ticket_id)
        if c.run != 1 or c.model == baseline or not c.ok or b is None:
            continue
        if c.category != b.category:
            category_diff.add(c.ticket_id)
        elif c.answer() != b.answer():
            flag_diff.add(c.ticket_id)

    ordered: list[str] = []
    for group in (decided_ids, category_diff, flag_diff):
        ordered.extend(tid for tid in sorted(group) if tid not in ordered)
    return ordered[:cap]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _mean(values: list) -> float | None:
    return statistics.fmean(values) if values else None


def _p90(values: list) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def short_answer(c: Call) -> str:
    """Deny, Admit(cheat), Review(cheat,exploit) — a category plus any flags."""
    flags = [name for name, on in (("cheat", c.admitted_cheating),
                                   ("exploit", c.admitted_exploit)) if on]
    text = SHORT.get(c.category, str(c.category))
    return f"{text}({','.join(flags)})" if flags else text


def tally(calls: list[Call]) -> str:
    """'Deny x2, Admit(cheat) x1' for one model's runs on one ticket."""
    counts = Counter(short_answer(c) for c in calls if c.ok)
    failed = sum(1 for c in calls if not c.ok)
    parts = [f"{answer} x{n}" for answer, n in counts.most_common()]
    if failed:
        parts.append(f"failed x{failed}")
    return ", ".join(parts) or "-"


def summarize(calls: list[Call], specs: list[ModelSpec], decided_ids: set[str],
              recheck_ids: list[str]) -> dict:
    """Everything the report prints, as plain data for the results file."""
    baseline = specs[0].label
    by_model = {s.label: [c for c in calls if c.model == s.label] for s in specs}
    first = {s.label: {c.ticket_id: c for c in by_model[s.label] if c.run == 1}
             for s in specs}

    models = {}
    for spec in specs:
        runs = by_model[spec.label]
        main = list(first[spec.label].values())
        answered = [c for c in main if c.ok]
        main_costs = [cost_usd(spec.model, c.input_tokens, c.output_tokens) for c in main]
        all_costs = [cost_usd(spec.model, c.input_tokens, c.output_tokens) for c in runs]
        models[spec.label] = {
            "tickets": len(main),
            "answered": len(answered),
            "failures": dict(Counter(c.failure for c in main if not c.ok)),
            "auto_deny_overrides": sum(1 for c in answered if c.final_category != c.category),
            "mean_confidence": _mean([c.confidence for c in answered]),
            "mean_input_tokens": _mean([c.input_tokens for c in main if c.input_tokens is not None]),
            "mean_output_tokens": _mean([c.output_tokens for c in main if c.output_tokens is not None]),
            "median_seconds": statistics.median([c.seconds for c in answered]) if answered else None,
            "p90_seconds": _p90([c.seconds for c in answered]),
            "cost_per_ticket": _mean([x for x in main_costs if x is not None]),
            "unpriced_calls": sum(1 for x in all_costs if x is None),
            "spend": sum(x for x in all_costs if x is not None),
        }

    versus = {}
    for spec in specs[1:]:
        pairs = [(b, first[spec.label][tid]) for tid, b in first[baseline].items()
                 if b.ok and tid in first[spec.label] and first[spec.label][tid].ok]
        decided = [(b, c) for b, c in pairs if b.ticket_id in decided_ids]
        confusion: dict[str, dict[str, int]] = {}
        for b, c in pairs:
            row = confusion.setdefault(b.category, {})
            row[c.category] = row.get(c.category, 0) + 1
        versus[spec.label] = {
            "compared": len(pairs),
            "same_category": sum(1 for b, c in pairs if b.category == c.category),
            "same_final_category": sum(1 for b, c in pairs if b.final_category == c.final_category),
            "same_admitted_cheating": sum(1 for b, c in pairs if b.admitted_cheating == c.admitted_cheating),
            "same_admitted_exploit": sum(1 for b, c in pairs if b.admitted_exploit == c.admitted_exploit),
            "same_answer": sum(1 for b, c in pairs if b.answer() == c.answer()),
            "model_decided_compared": len(decided),
            "model_decided_same_final": sum(1 for b, c in decided if b.final_category == c.final_category),
            "confusion": confusion,
            "disagreements": [b.ticket_id for b, c in pairs if b.answer() != c.answer()],
        }

    stability = {}
    for spec in specs:
        per_ticket = {tid: [c for c in by_model[spec.label] if c.ticket_id == tid]
                      for tid in recheck_ids}
        judged = {tid: runs for tid, runs in per_ticket.items()
                  if sum(1 for c in runs if c.ok) >= 2}
        stability[spec.label] = {
            "rechecked": len(judged),
            "stable": sum(1 for runs in judged.values()
                          if len({c.answer() for c in runs if c.ok}) == 1),
            "tallies": {tid: tally(runs) for tid, runs in per_ticket.items()},
        }

    return {"models": models, "versus_baseline": versus, "stability": stability}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

BAR = "=" * 78
RULE = "-" * 78


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100.0 * n / d:.0f}%)" if d else "-"


def _num(value, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def print_report(summary: dict, specs: list[ModelSpec], samples: list,
                 calls: list[Call], recheck_ids: list[str], elapsed: float,
                 stopped: str | None) -> None:
    baseline = specs[0].label
    bans = {t["ticket_id"]: b for t, b in samples}
    first = {(c.model, c.ticket_id): c for c in calls if c.run == 1}

    print(f"\n{BAR}")
    print(f"MODEL COMPARISON — {len(samples)} sample tickets, baseline {baseline}")
    if stopped:
        print(f"(stopped early, partial results: {stopped})")
    print(BAR)
    decided = sum(1 for _, b in samples if model_decided(b))
    print(f"{decided} of {len(samples)} tickets are model-decided; on the rest a confirmed "
          f"detection\nmeans the auto-deny rule sets the final category.")

    for spec in specs:
        m = summary["models"][spec.label]
        print(f"\n{spec.label}{'  (baseline)' if spec.label == baseline else ''}")
        print(f"  Answered:              {_pct(m['answered'], m['tickets'])}")
        for failure, n in sorted(m["failures"].items()):
            print(f"    failed, {failure}: {n}")
        print(f"  Auto-deny overrides:   {m['auto_deny_overrides']}")
        print(f"  Mean confidence:       {_num(m['mean_confidence'], '.2f')}")
        print(f"  Mean tokens in / out:  {_num(m['mean_input_tokens'], ',.0f')} / "
              f"{_num(m['mean_output_tokens'], ',.0f')}")
        print(f"  Seconds per answer:    median {_num(m['median_seconds'], '.1f')}, "
              f"p90 {_num(m['p90_seconds'], '.1f')}")
        per_ticket = m["cost_per_ticket"]
        print(f"  Cost per ticket:       {_num(per_ticket, '.5f')} USD"
              f"  (per 1,000 tickets: {_num(per_ticket and per_ticket * 1000, '.2f')} USD)")
        unpriced = f", {m['unpriced_calls']} call(s) unpriced" if m["unpriced_calls"] else ""
        print(f"  Spent this run:        {m['spend']:.4f} USD{unpriced}")

    for spec in specs[1:]:
        v = summary["versus_baseline"][spec.label]
        print(f"\n{RULE}\n{spec.label} vs {baseline}  (tickets both answered: {v['compared']})")
        for label, key in (("Same own category:", "same_category"),
                           ("Same final category:", "same_final_category"),
                           ("Same admitted_cheating:", "same_admitted_cheating"),
                           ("Same admitted_exploit:", "same_admitted_exploit"),
                           ("Same on all three:", "same_answer")):
            print(f"  {label:24s}{_pct(v[key], v['compared'])}")
        print(f"  Model-decided tickets, same final category: "
              f"{_pct(v['model_decided_same_final'], v['model_decided_compared'])}")
        if v["disagreements"]:
            print("  Where they differ (run 1; re-check tallies cover every run):")
            for tid in v["disagreements"]:
                b, c = first[(baseline, tid)], first[(spec.label, tid)]
                method = (bans[tid] or {}).get("detection_method", "no ban record")
                print(f"    {tid}  [{method}]  baseline {short_answer(b)} "
                      f"{b.confidence:.2f}  vs  {short_answer(c)} {c.confidence:.2f}")
                st = summary["stability"]
                if tid in recheck_ids:
                    print(f"      re-check: baseline {st[baseline]['tallies'][tid]}"
                          f"  |  this model {st[spec.label]['tallies'][tid]}")

    if recheck_ids:
        print(f"\n{RULE}\nRe-check: {len(recheck_ids)} ticket(s), every model, "
              f"all runs. Same answer every run:")
        for spec in specs:
            s = summary["stability"][spec.label]
            print(f"  {spec.label:28s} {_pct(s['stable'], s['rechecked'])}")

    failed = [c for c in calls if not c.ok]
    if failed:
        print(f"\n{RULE}\nFailures:")
        for c in failed:
            print(f"  {c.ticket_id}  {c.model}  run {c.run}  {c.failure}")
            if c.failure not in (NO_ANSWER, CUT_OFF) and c.error:
                print(f"      {c.error.splitlines()[0][:110]}")

    spend = sum(m["spend"] for m in summary["models"].values())
    unpriced = sum(m["unpriced_calls"] for m in summary["models"].values())
    print(f"\nTotal spent: {spend:.4f} USD over {len(calls)} calls"
          + (f" ({unpriced} unpriced: no usage reported)" if unpriced else ""))
    print(f"Elapsed: {elapsed / 60:.1f} min")
    print(BAR)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", metavar="NAME[@BUDGET]",
                        help="models to compare, baseline first "
                             "(default: MODEL_NAME, claude-haiku-5-5, claude-haiku-5-5@8000)")
    parser.add_argument("--provider", help="override LLM_PROVIDER (anthropic or openai)")
    parser.add_argument("--limit", type=int, help="only the first N tickets")
    parser.add_argument("--recheck", type=int, default=2,
                        help="extra runs per model on contested tickets (default 2; 0 skips)")
    parser.add_argument("--out", type=Path,
                        help="results file (default model-comparison-<timestamp>.json)")
    args = parser.parse_args()

    # Ticket bodies contain smart quotes and em-dashes; Windows consoles
    # default to cp1252.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if args.provider:
        settings.LLM_PROVIDER = args.provider.strip().lower()
    if not args.models:
        if settings.LLM_PROVIDER != "anthropic":
            parser.error("the default models are Claude models; pass --models "
                         f"for LLM_PROVIDER={settings.LLM_PROVIDER}")
        if not settings.MODEL_NAME:
            parser.error("MODEL_NAME is not set; set it or pass --models")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.recheck < 0:
        parser.error("--recheck can't be negative")

    texts = args.models or [settings.MODEL_NAME, *DEFAULT_CHALLENGERS]
    try:
        parsed = [parse_spec(t, settings.LLM_MAX_TOKENS) for t in texts]
    except ValueError as e:
        parser.error(str(e))
    specs = list(dict.fromkeys(parsed))  # drop repeats, keep order
    out = args.out or Path(f"model-comparison-{datetime.now():%Y%m%d-%H%M%S}.json")

    try:
        get_provider()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    samples = load_samples(SAMPLE_TICKETS, SAMPLE_BANS)[:args.limit]
    decided_ids = {t["ticket_id"] for t, b in samples if model_decided(b)}
    print(f"Comparing {', '.join(s.label for s in specs)} on {len(samples)} tickets "
          f"via {settings.LLM_PROVIDER}.\nBaseline: {specs[0].label}. Results file: {out}")

    # evaluate_ticket() reads the model and budget from settings at call
    # time, so switching them between models is enough.
    recorder = UsageRecorder(evaluator.call_model)
    evaluator.call_model = recorder
    calls: list[Call] = []
    recheck_ids: list[str] = []
    stopped = None  # why the run ended early, when it did
    started = time.monotonic()

    def run_model(spec: ModelSpec, run: int, batch: list) -> None:
        settings.MODEL_NAME, settings.LLM_MAX_TOKENS = spec.model, spec.budget
        for i, (ticket, ban) in enumerate(batch, start=1):
            call = run_one(spec, ticket, ban, run, recorder)
            calls.append(call)
            if call.ok:
                outcome = f"{short_answer(call)} {call.confidence:.2f}"
                if call.final_category != call.category:
                    final = SHORT.get(call.final_category, call.final_category)
                    outcome += f" -> {final} (auto-deny rule)"
            else:
                outcome = f"FAILED: {call.failure}"
            print(f"  [{spec.label} run {run}  {i}/{len(batch)}] {ticket['ticket_id']}  "
                  f"{outcome}  {call.seconds:.1f}s", flush=True)

    try:
        for spec in specs:
            run_model(spec, 1, samples)
        if args.recheck and len(specs) > 1:
            recheck_ids = pick_recheck(calls, specs[0].label, decided_ids, RECHECK_CAP)
            batch = [(t, b) for t, b in samples if t["ticket_id"] in recheck_ids]
            print(f"\nRe-checking {len(batch)} ticket(s), {args.recheck} more run(s) per model.")
            for spec in specs:
                for run in range(2, args.recheck + 2):
                    run_model(spec, run, batch)
    except AbortRun as e:
        stopped = f"{e} (every remaining call would fail the same way)"
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        evaluator.call_model = recorder._call
    if stopped and not calls:
        print(f"\nERROR: {stopped}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    summary = summarize(calls, specs, decided_ids, recheck_ids)
    out.write_text(json.dumps({
        "run": {
            "finished": datetime.now().isoformat(timespec="seconds"),
            "provider": settings.LLM_PROVIDER,
            "models": [asdict(s) | {"label": s.label} for s in specs],
            "baseline": specs[0].label,
            "tickets": len(samples),
            "rechecked_tickets": recheck_ids,
            "elapsed_seconds": round(elapsed, 1),
            "stopped_early": stopped,
        },
        "tickets": {
            t["ticket_id"]: {
                "title": t["ticket_title"],
                "issue_category": t["ticket_issue_category"],
                "detection_method": b["detection_method"] if b else None,
                "model_decided": t["ticket_id"] in decided_ids,
            }
            for t, b in samples
        },
        "summary": summary,
        "calls": [asdict(c) for c in calls],
    }, indent=2), encoding="utf-8")

    print_report(summary, specs, samples, calls, recheck_ids, elapsed, stopped)
    print(f"Every call, with summaries and reasoning: {out}")
    if stopped:
        print(f"\nStopped early: {stopped}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
