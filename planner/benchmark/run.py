"""Benchmark the planner in three layers.

rules    the verdict rules, the evaluator's rule checks on drafts with planted
         errors, and the replan rules, on hand-written cases (no services)
compose  the composer and evaluator loop on the findings saved from three real
         trips (fixtures/): figure-check rejections, template fallbacks,
         evaluator rounds and verdicts, latency (Nightshift only)
e2e      full plans for the same three trips (Zetaris, Nightshift and the
         weather service); live data, so the verdict may differ from the capture

Results print as a summary and are written to results-<timestamp>.json here.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from wastewater_agent.config import Settings
from wastewater_agent.llm import NightshiftProvider, ProviderError

from .. import evaluator
from ..composer import allowed_for, compose, render_sheet, verdict_for
from ..findings import TITLES, Finding
from ..trip import TripRequest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
LAYERS = ("rules", "compose", "e2e")
DEFAULT_LAYERS = ("rules", "compose")


# -- cases ---------------------------------------------------------------------

def finding(source: str, level: str = "low", status: str = "ok", raw: dict[str, Any] | None = None) -> Finding:
    meaning = f"{TITLES[source]} is {level}." if status == "ok" else ""
    return Finding(source=source, title=TITLES[source], status=status, level=level, headline=f"{TITLES[source]}: {level}",
                   meaning=meaning, error=None if status == "ok" else "timed out", raw=raw or {})


def trip(*groups: str) -> TripRequest:
    return TripRequest(to_city="Richmond", to_state="va", from_city="Austin", from_state="tx",
                       start=date(2026, 11, 10), end=date(2026, 11, 17), to_county="Richmond City", with_=groups)


def findings_with(**levels: str) -> list[Finding]:
    """Every source low unless given; a value of 'failed' makes that source an error."""
    out = []
    for s in ("covid", "flu", "pertussis", "weather", "guidance"):
        lv = levels.get(s, "unknown" if s == "guidance" else "low")
        out.append(finding(s, status="error", level="high") if lv == "failed" else finding(s, lv))
    return out


# (name, household groups, findings, expected level, text the reason must contain)
VERDICT_CASES: list[tuple[str, tuple[str, ...], list[Finding], str, str | None]] = [
    ("all low", (), findings_with(), "low", "Every source with data is at a low level"),
    ("weather moderate", (), findings_with(weather="moderate"), "moderate", None),
    ("covid high", (), findings_with(covid="high"), "high", None),
    ("flu moderate, older adult in household", ("older_adult",), findings_with(flu="moderate"), "high",
     "Counted as high because the household includes older adults"),
    ("pertussis moderate, newborn in household", ("newborn",), findings_with(pertussis="moderate"), "high", None),
    ("weather moderate, newborn: weather is not escalated", ("newborn",), findings_with(weather="moderate"), "moderate", None),
    ("pertussis moderate, no stated group", (), findings_with(pertussis="moderate"), "moderate", None),
    ("guidance never sets the level", (), [finding("guidance", "high")], "unknown", None),
    ("a failed source is ignored even if it carries a level", (), findings_with(covid="failed"), "low", None),
    ("every source failed", (), findings_with(covid="failed", flu="failed", pertussis="failed", weather="failed"),
     "unknown", "None of the sources had enough recent data"),
]

# The evaluator's rule checks: one clean draft, then drafts with one planted error each.
CLEAN_INTRO = "COVID-19 in Richmond's wastewater is high, so this visit needs full precautions."
CLEAN_PRECAUTIONS = [
    "Wear a well-fitted mask on the journey and in crowded indoor places.",
    "Keep hand hygiene strict around your older relatives.",
    "Check the wastewater readings again a few days before you travel.",
    "Air the rooms you share and keep gatherings small.",
    "Stay home if you have symptoms.",
]


def _drop_group(precautions: list[str]) -> list[str]:
    return [p for p in precautions if "older" not in p]


# (name, intro, precautions, the issue the rules must raise, or None for the clean draft)
DRAFT_CASES: list[tuple[str, str, list[str], str | None]] = [
    ("clean draft", CLEAN_INTRO, CLEAN_PRECAUTIONS, None),
    ("figure not in the fact sheet", CLEAN_INTRO.replace("high,", "high at 87% of samples,"), CLEAN_PRECAUTIONS,
     "figures that are not in the fact sheet"),
    ("N95 read as a figure", CLEAN_INTRO, ["Wear an N95 mask on the journey."] + CLEAN_PRECAUTIONS[1:],
     "figures that are not in the fact sheet"),
    ("intro contradicts the verdict", CLEAN_INTRO + " Overall you are good to go.", CLEAN_PRECAUTIONS, "contradicts it"),
    ("no precaution for the stated group", CLEAN_INTRO, _drop_group(CLEAN_PRECAUTIONS) + ["Pack layers."],
     "Add a precaution specifically for the older adults"),
    ("failed source described as fine", CLEAN_INTRO + " Flu levels are low as well.", CLEAN_PRECAUTIONS,
     "was not available for this plan"),
    ("destination not named", "Wastewater readings are high, so this visit needs full precautions.", CLEAN_PRECAUTIONS,
     "Name the destination"),
    ("too few precautions", CLEAN_INTRO, CLEAN_PRECAUTIONS[:2], "Give between 5 and 8 precautions"),
]


def _empty_county(source: str, county: str | None) -> Finding:
    return finding(source, "unknown", raw={"coverage": "empty", "facts": {"county": county}})


# (name, findings by source, expected [(source, action)])
REPLAN_CASES: list[tuple[str, dict[str, Finding], list[tuple[str, str]]]] = [
    ("everything answered", {f.source: f for f in findings_with()}, []),
    ("a source failed: retry it", {"covid": finding("covid", status="error"), "weather": finding("weather")},
     [("covid", "retry")]),
    ("no recent county samples: ask at state level", {"flu": _empty_county("flu", "Richmond City")},
     [("flu", "state_level")]),
    ("no samples but already state level: leave it", {"flu": _empty_county("flu", None)}, []),
    ("a skipped source is left alone", {"weather": finding("weather", status="skipped")}, []),
]

# usefulness() decides whether a re-asked answer replaces the first one.
KEEP_CASES: list[tuple[str, Finding, Finding, bool]] = [
    ("state-level answer with a level replaces an empty county answer", _empty_county("flu", "Richmond City"),
     finding("flu", "moderate"), True),
    ("a failed retry never replaces an answer", finding("covid", "unknown"), finding("covid", status="error"), False),
    ("an equally empty answer keeps the first", _empty_county("covid", "X"), finding("covid", "unknown"), False),
]


# -- results ---------------------------------------------------------------------

@dataclass
class RuleResult:
    group: str          # verdict | draft | replan | keep
    name: str
    ok: bool
    expected: Any
    got: Any


@dataclass
class ComposeResult:
    fixture: str
    run: int
    expected_level: str
    level: str
    composer_model: str          # the chosen draft's writer, "template" on fallback
    first_draft_model: str
    drafts: int
    final: str                   # pass | revise
    figure_rejections: int       # composer attempts rejected by the figure check
    foreign_figures: list[str]
    json_failures: int
    rule_issues: list[str]       # rule issues across all reviews
    model_issues: list[str]
    latency_s: float
    error: str | None = None

    @property
    def model_written(self) -> bool:
        return self.composer_model != "template"


@dataclass
class E2EResult:
    fixture: str
    expected_level: str          # the level captured in the fixture
    level: str | None
    partial: bool | None
    sources_ok: int
    composer_model: str | None
    final: str | None
    replans: int
    latency_s: float
    error: str | None = None


@dataclass
class Report:
    started_at: str
    layers: list[str]
    repeats: int
    rules: list[RuleResult] = field(default_factory=list)
    compose: list[ComposeResult] = field(default_factory=list)
    e2e: list[E2EResult] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def rows(items: list[Any]) -> list[dict[str, Any]]:
            return [dict(vars(r), **({"model_written": r.model_written} if hasattr(r, "model_written") else {}))
                    for r in items]

        return {"startedAt": self.started_at, "layers": self.layers, "repeats": self.repeats,
                "summary": self.summary, "skipped": self.skipped,
                "rules": rows(self.rules), "compose": rows(self.compose), "e2e": rows(self.e2e)}


# -- runner ------------------------------------------------------------------------

FIGURES = re.compile(r"figures not in the fact sheet \(([^)]*)\)")


def load_fixtures() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))]


def fixture_findings(fx: dict[str, Any]) -> dict[str, Finding]:
    return {d["source"]: Finding(**d) for d in fx["findings"]}


class Benchmark:
    def __init__(self, settings: Settings, *, layers: list[str], repeats: int = 1,
                 weather_url: str | None = None, log=print) -> None:
        self.settings = settings
        self.layers = [l for l in LAYERS if l in layers]
        self.repeats = max(1, repeats)
        self.weather_url = weather_url
        self.log = log
        self.fixtures = load_fixtures()
        self.report = Report(started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                             layers=self.layers, repeats=self.repeats)

    def run(self) -> Report:
        if "rules" in self.layers:
            self._run_rules()
        if "compose" in self.layers:
            self._run_compose()
        if "e2e" in self.layers:
            self._run_e2e()
        self._summarise()
        return self.report

    # -- layer 1: rules ------------------------------------------------------------

    def _rule(self, group: str, name: str, expected: Any, got: Any, ok: bool | None = None) -> None:
        ok = (expected == got) if ok is None else ok
        self.report.rules.append(RuleResult(group, name, ok, expected, got))
        self.log(f"  {'ok  ' if ok else 'FAIL'} {group:7} {name}" + ("" if ok else f"  expected {expected!r}, got {got!r}"))

    def _run_rules(self) -> None:
        n = len(VERDICT_CASES) + len(DRAFT_CASES) + len(REPLAN_CASES) + len(KEEP_CASES)
        self.log(f"\n[rules] {n} cases")
        for name, groups, fs, level, reason_part in VERDICT_CASES:
            v = verdict_for(trip(*groups), fs)
            reason_ok = reason_part is None or reason_part in v.reason
            self._rule("verdict", name, level, v.level if reason_ok else f"{v.level}; reason: {v.reason}",
                       ok=v.level == level and reason_ok)

        t = trip("older_adult")
        fs = findings_with(covid="high", flu="failed")
        v = verdict_for(t, fs)
        sheet = render_sheet(t, fs, v)
        allowed = allowed_for(t, sheet)
        for name, intro, prec, want in DRAFT_CASES:
            issues = evaluator.rule_checks(t, fs, v, intro, prec, allowed)
            if want is None:
                self._rule("draft", name, [], issues)
            else:
                caught = [i for i in issues if want in i]
                # Caught, and nothing else raised: the planted error is the only fault in the draft.
                self._rule("draft", name, [want], issues, ok=bool(caught) and len(issues) == len(caught))

        for name, by_source, want in REPLAN_CASES:
            got = [(r.source, r.action) for r in evaluator.review_findings(trip(), by_source)]
            self._rule("replan", name, want, got)

        for name, old, new, want in KEEP_CASES:
            self._rule("keep", name, want, evaluator.usefulness(new) > evaluator.usefulness(old))

    # -- layer 2: compose ------------------------------------------------------------

    def _provider(self) -> NightshiftProvider | None:
        ns = NightshiftProvider(self.settings.nightshift_base_url, self.settings.nightshift_token,
                                models=self.settings.nightshift_models)
        state, _ = ns.readiness()
        if state != "online":
            self.report.skipped["compose"] = f"Nightshift {state}"
            self.log(f"nightshift: {state}; skipping the compose layer")
            return None
        return ns

    def _run_compose(self) -> None:
        provider = self._provider()
        if provider is None:
            return
        self.log(f"\n[compose] {len(self.fixtures)} trips x {self.repeats}")
        for fx in self.fixtures:
            t = TripRequest.from_dict(fx["trip"])
            for r in range(1, self.repeats + 1):
                t0 = time.perf_counter()
                try:
                    plan = compose(t, fixture_findings(fx), provider)
                except ProviderError as e:
                    self.report.compose.append(ComposeResult(fx["name"], r, fx["expectedLevel"], "?", "?", "?", 0, "?",
                                                             0, [], 0, [], [], time.perf_counter() - t0, error=str(e)))
                    self.log(f"  {fx['name']} #{r}: error {e}")
                    continue
                dt = time.perf_counter() - t0
                ev = plan.evaluation
                rounds = ev.get("rounds", [])
                foreign = [x.strip() for n in plan.notes for m in FIGURES.finditer(n) for x in m.group(1).split(",")]
                res = ComposeResult(
                    fixture=fx["name"], run=r, expected_level=fx["expectedLevel"], level=plan.verdict.level,
                    composer_model=plan.models["composer"] or "template",
                    first_draft_model=rounds[0]["draft_model"] if rounds else "?",
                    drafts=len(rounds), final=ev.get("final", "?"),
                    figure_rejections=sum(bool(FIGURES.search(n)) for n in plan.notes), foreign_figures=foreign,
                    json_failures=sum("not the expected JSON" in n for n in plan.notes),
                    rule_issues=[i for rd in rounds for i in rd["rule_issues"]],
                    model_issues=[i for rd in rounds for i in rd["model_issues"]],
                    latency_s=dt,
                )
                self.report.compose.append(res)
                self.log(f"  {fx['name']} #{r}: {res.level} (expected {res.expected_level})  writer {res.composer_model}  "
                         f"drafts {res.drafts}  final {res.final}  figure rejections {res.figure_rejections}"
                         + (f" ({', '.join(sorted(set(foreign)))})" if foreign else "") + f"  {dt:.0f}s")

    # -- layer 3: e2e ----------------------------------------------------------------

    def _run_e2e(self) -> None:
        from ..planner_agent import PlannerAgent

        self.log(f"\n[e2e] {len(self.fixtures)} trips")
        planner = PlannerAgent(self.settings, weather_url=self.weather_url)
        try:
            for fx in self.fixtures:
                t0 = time.perf_counter()
                try:
                    plan = planner.run(TripRequest.from_dict(fx["trip"]))
                except Exception as e:  # noqa: BLE001  one failed trip must not end the run
                    self.report.e2e.append(E2EResult(fx["name"], fx["expectedLevel"], None, None, 0, None, None, 0,
                                                     time.perf_counter() - t0, error=f"{e.__class__.__name__}: {e}"[:300]))
                    self.log(f"  {fx['name']}: error {e}")
                    continue
                dt = time.perf_counter() - t0
                res = E2EResult(
                    fixture=fx["name"], expected_level=fx["expectedLevel"], level=plan.verdict.level,
                    partial=plan.partial, sources_ok=sum(s.status == "ok" for s in plan.sections),
                    composer_model=plan.models["composer"], final=plan.evaluation.get("final"),
                    replans=sum(len(rp["requests"]) for rp in plan.evaluation.get("replans") or []), latency_s=dt,
                )
                self.report.e2e.append(res)
                self.log(f"  {fx['name']}: {res.level} (captured {res.expected_level})  sources ok {res.sources_ok}/5  "
                         f"writer {res.composer_model}  final {res.final}  {dt:.0f}s")
        finally:
            planner.close()

    # -- summary ---------------------------------------------------------------------

    def _summarise(self) -> None:
        s: dict[str, Any] = {}
        if self.report.rules:
            by = Counter()
            ok = Counter()
            for r in self.report.rules:
                by[r.group] += 1
                ok[r.group] += r.ok
            s["rules"] = {g: f"{ok[g]}/{by[g]}" for g in by} | {"all": f"{sum(ok.values())}/{sum(by.values())}"}
        c = [r for r in self.report.compose if not r.error]
        if self.report.compose:
            s["compose"] = {
                "runs": len(self.report.compose),
                "errors": len(self.report.compose) - len(c),
                "verdict_match": sum(r.level == r.expected_level for r in c),
                "first_draft_model_written": sum(r.first_draft_model != "template" for r in c),
                "model_written": sum(r.model_written for r in c),
                "template_fallback": sum(not r.model_written for r in c),
                "figure_rejections": sum(r.figure_rejections for r in c),
                # In how many runs each rejected figure appeared (a run repeats it in every attempt).
                "foreign_figures": dict(Counter(x for r in c for x in set(r.foreign_figures)).most_common(5)),
                "evaluator_pass": sum(r.final == "pass" for r in c),
                "median_drafts": statistics.median(r.drafts for r in c) if c else None,
                "median_latency_s": round(statistics.median(r.latency_s for r in c), 1) if c else None,
            }
        e = [r for r in self.report.e2e if not r.error]
        if self.report.e2e:
            s["e2e"] = {
                "runs": len(self.report.e2e),
                "errors": len(self.report.e2e) - len(e),
                "complete": sum(not r.partial for r in e),
                "verdict_as_captured": sum(r.level == r.expected_level for r in e),
                "model_written": sum(r.composer_model not in (None, "template") for r in e),
                "evaluator_pass": sum(r.final == "pass" for r in e),
                "median_latency_s": round(statistics.median(r.latency_s for r in e), 1) if e else None,
            }
        self.report.summary = s


def print_summary(report: Report, log=print) -> None:
    s = report.summary
    log("\n=== summary ===")
    if "rules" in s:
        log("rules:   " + "  ".join(f"{g} {v}" for g, v in s["rules"].items()))
    if "compose" in s:
        c = s["compose"]
        log(f"compose: verdict {c['verdict_match']}/{c['runs'] - c['errors']}  model-written {c['model_written']}  "
            f"template fallback {c['template_fallback']}  evaluator pass {c['evaluator_pass']}  "
            f"figure rejections {c['figure_rejections']} {c['foreign_figures'] or ''}  "
            f"median drafts {c['median_drafts']}  median {c['median_latency_s']}s")
    if "e2e" in s:
        e = s["e2e"]
        log(f"e2e:     complete {e['complete']}/{e['runs']}  verdict as captured {e['verdict_as_captured']}  "
            f"model-written {e['model_written']}  evaluator pass {e['evaluator_pass']}  median {e['median_latency_s']}s")
    for layer, why in report.skipped.items():
        log(f"skipped: {layer}: {why[:120]}")
