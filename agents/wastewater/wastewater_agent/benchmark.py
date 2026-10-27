"""Benchmark the agent in three layers.

plan    planner accuracy: intent, state and window against an expected plan
        (Nightshift only; no database needed)
answer  answer fidelity: first-attempt figure-check pass rate, retries,
        template fallbacks, coverage, latency, and a meterless/judge score
        (needs Zetaris)
memory  cross-session recall: a second, fresh agent asks the same question and
        must use the memory the first run stored (needs Zetaris)

Results print as a table and are written to a JSON file. The benchmark uses
its own memory directory so it never touches the agent's real .hmem.
"""

from __future__ import annotations

import calendar
import json
import re
import shutil
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .agent import Agent
from .agent import planner, windows
from .agent.writer import render_facts
from .config import AGENT_ROOT, Settings
from .llm import NightshiftProvider, OfflineProvider, ProviderError
from .zetaris import ZetarisError

DEFAULT_QUESTIONS = AGENT_ROOT / "benchmark" / "questions.json"
DEFAULT_HMEM_DIR = AGENT_ROOT / ".hmem_bench"
JUDGE_MODEL = "meterless/judge"
LAYERS = ("plan", "answer", "memory")

JUDGE_SYSTEM = """You are a strict judge of a short public-health answer.
Score the CANDIDATE against the FACT SHEET:
- fidelity 0-10: every figure in the candidate must appear in the fact sheet exactly (nothing invented, estimated or re-rounded); 10 = all figures match, 0 = a figure is wrong or invented.
- clarity 0-10: a general reader understands the window, the region and the finding.
Reply with only JSON: {"fidelity": n, "clarity": n, "foreign_figures": [...], "verdict": "accept" | "reject", "reason": "..."}"""


# -- question set ---------------------------------------------------------------


@dataclass
class Question:
    id: str
    question: str
    intent: str
    state: str | None
    window: Any  # spec string, dict, or "any"
    pathogen: str = "sars-cov-2"


def load_questions(path: Path) -> list[Question]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Question] = []
    for q in data["questions"]:
        e = q["expect"]
        out.append(Question(q["id"], q["question"], e["intent"], e.get("state"), e.get("window", "any"), e.get("pathogen", "sars-cov-2")))
    return out


def expected_window(spec: Any, today: date) -> tuple[date, date] | None:
    """None means any valid window is acceptable."""
    yesterday = today - timedelta(days=1)
    if spec in (None, "any"):
        return None
    if isinstance(spec, dict):
        return date.fromisoformat(spec["start"]), date.fromisoformat(spec["end"])
    if spec == "last_week":
        w = windows.default_window(today)
        return w.start, w.end
    if spec == "yesterday":
        return yesterday, yesterday
    if spec == "this_month":
        return min(today.replace(day=1), yesterday), yesterday
    if spec == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if m := re.fullmatch(r"last_(\d+)_days", spec):
        n = int(m.group(1))
        return yesterday - timedelta(days=n - 1), yesterday
    if m := re.fullmatch(r"month:(\d{4})-(\d{2})", spec):
        y, mo = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1), min(date(y, mo, calendar.monthrange(y, mo)[1]), today)
    raise ValueError(f"unknown window spec {spec!r}")


# -- results -------------------------------------------------------------------


@dataclass
class PlanResult:
    id: str
    repeat: int
    intent: str
    state: str | None
    window: str
    source: str
    routed_model: str | None
    receipt_id: str | None
    intent_ok: bool
    state_ok: bool
    window_ok: bool
    notes: list[str]
    latency_s: float
    pathogen_ok: bool = True
    pathogen: str = "sars-cov-2"

    @property
    def ok(self) -> bool:
        return self.intent_ok and self.state_ok and self.window_ok and self.pathogen_ok


@dataclass
class AnswerResult:
    id: str
    provider: str
    plan_source: str
    coverage: str
    write_attempts: int
    first_pass: bool
    retry_pass: bool
    fallback: bool
    foreign_figures: list[str]
    routed_models: list[str]
    receipt_ids: list[str]
    memory_id: str | None
    latency_s: float
    judge: dict[str, Any] | None = None
    judge_receipt: str | None = None
    error: str | None = None


@dataclass
class MemoryResult:
    id: str
    first_memory: str | None
    recalled: list[str]
    hit: bool
    superseded_outranked: bool | None
    latency_s: float
    error: str | None = None


@dataclass
class Report:
    started_at: str
    today: str
    layers: list[str]
    repeats: int
    plan: list[PlanResult] = field(default_factory=list)
    answer: list[AnswerResult] = field(default_factory=list)
    memory: list[MemoryResult] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        def rows(items: list[Any]) -> list[dict[str, Any]]:
            return [dict(vars(r), **({"ok": r.ok} if hasattr(r, "ok") else {})) for r in items]

        return {
            "startedAt": self.started_at,
            "today": self.today,
            "layers": self.layers,
            "repeats": self.repeats,
            "summary": self.summary,
            "skipped": self.skipped,
            "plan": rows(self.plan),
            "answer": rows(self.answer),
            "memory": rows(self.memory),
        }


# -- runner --------------------------------------------------------------------


class Benchmark:
    def __init__(
        self,
        settings: Settings,
        questions: list[Question],
        *,
        layers: list[str],
        repeats: int = 1,
        judge: bool = True,
        hmem_dir: Path = DEFAULT_HMEM_DIR,
        today: date | None = None,
        log=print,
    ) -> None:
        self.settings = settings
        self.questions = questions
        self.layers = [l for l in LAYERS if l in layers]
        self.repeats = max(1, repeats)
        self.judge = judge
        self.hmem_dir = hmem_dir
        self.today = today or date.today()
        self.log = log
        self.offline = OfflineProvider()
        self.nightshift = NightshiftProvider(settings.nightshift_base_url, settings.nightshift_token, models=settings.nightshift_models)
        self.judge_provider = NightshiftProvider(settings.nightshift_base_url, settings.nightshift_token, model=JUDGE_MODEL)
        self.report = Report(
            started_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            today=self.today.isoformat(),
            layers=self.layers,
            repeats=self.repeats,
        )

    # -- entry -----------------------------------------------------------------

    def run(self) -> Report:
        state, _ = self.nightshift.readiness()
        provider = self.nightshift if state == "online" else None
        if provider is None:
            self.log(f"nightshift: {state}; the planner and writer will use the offline fallback")
        if "plan" in self.layers:
            self._run_plan(provider)
        if "answer" in self.layers or "memory" in self.layers:
            self._run_answer_and_memory(provider is not None)
        self._summarise()
        return self.report

    # -- layer 1: plan ---------------------------------------------------------

    def _run_plan(self, provider) -> None:
        self.log(f"\n[plan] {len(self.questions)} questions x {self.repeats}")
        for q in self.questions:
            exp = expected_window(q.window, self.today)
            for r in range(1, self.repeats + 1):
                hint = windows.resolve(q.question, self.today)
                t0 = time.perf_counter()
                try:
                    plan, completion, reason = planner.plan(q.question, hint, self.today, provider, self.offline)
                except ProviderError as e:
                    plan, completion, reason = None, None, str(e)
                dt = time.perf_counter() - t0
                if plan is None:
                    res = PlanResult(q.id, r, "?", None, "?", "error", None, None, False, False, False, [reason or ""], dt)
                else:
                    w_ok = exp is None or (plan.window.start, plan.window.end) == exp
                    res = PlanResult(
                        q.id, r, plan.intent, plan.state, str(plan.window), plan.source,
                        completion.routed_model if completion else None,
                        completion.receipt_id if completion else None,
                        plan.intent == q.intent, plan.state == q.state, w_ok,
                        list(plan.notes) + ([reason] if reason else []), dt,
                        pathogen_ok=(plan.pathogen == q.pathogen), pathogen=plan.pathogen,
                    )
                self.report.plan.append(res)
                mark = "ok " if res.ok else "MISS"
                self.log(f"  {mark} {q.id:<32} {res.intent:<6} {res.state or 'us':<3} {res.window:<22} {res.source:<10} {(res.routed_model or '-')[:38]:<38} {dt:5.1f}s")
                if not res.ok:
                    self.log(f"       expected intent={q.intent} state={q.state or 'us'} window={_fmt_exp(exp)} pathogen={q.pathogen} (got {res.pathogen})" + (f"  notes={res.notes}" if res.notes else ""))

    # -- layers 2 and 3: answer and memory ------------------------------------

    def _run_answer_and_memory(self, online: bool) -> None:
        if self.hmem_dir.exists():
            shutil.rmtree(self.hmem_dir)
        settings = Settings(**{**vars(self.settings), "hmem_dir": self.hmem_dir})
        first_memory: dict[str, str | None] = {}

        if "answer" in self.layers:
            self.log(f"\n[answer] {len(self.questions)} questions" + ("" if self.judge else " (judge off)"))
            agent = Agent(settings, today=self.today)
            try:
                for q in self.questions:
                    res = self._answer_one(agent, q)
                    self.report.answer.append(res)
                    first_memory[q.id] = res.memory_id
                    if res.error:
                        self.log(f"  ERR  {q.id:<32} {res.error[:90]}")
                        if "cannot connect" in res.error:
                            self.report.skipped["answer"] = res.error
                            self.report.skipped["memory"] = "needs the answer layer"
                            return
                        continue
                    pf = "first" if res.first_pass else ("retry" if res.retry_pass else "FALLBACK")
                    j = f"judge fid={res.judge.get('fidelity')} clr={res.judge.get('clarity')} {res.judge.get('verdict')}" if res.judge else "judge -"
                    self.log(f"  {q.id:<32} {res.provider:<10} cov={res.coverage:<7} figures={pf:<8} {j:<34} {res.latency_s:5.1f}s")
            finally:
                agent.close()

        if "memory" in self.layers:
            if "memory" in self.report.skipped:
                return
            self.log(f"\n[memory] second session asks the same {len(self.questions)} questions")
            agent2 = Agent(settings, today=self.today)  # fresh HMem instance loaded from disk
            try:
                for q in self.questions:
                    res = self._memory_one(agent2, q, first_memory.get(q.id))
                    self.report.memory.append(res)
                    if res.error:
                        self.log(f"  ERR  {q.id:<32} {res.error[:90]}")
                        if "cannot connect" in res.error:
                            self.report.skipped["memory"] = res.error
                            return
                        continue
                    self.log(f"  {'hit ' if res.hit else 'MISS'} {q.id:<32} stored={res.first_memory or '-':<17} recalled={len(res.recalled)} {res.latency_s:5.1f}s")
            finally:
                agent2.close()

    def _answer_one(self, agent: Agent, q: Question) -> AnswerResult:
        t0 = time.perf_counter()
        try:
            ans = agent.ask(q.question)
        except ZetarisError as e:
            return AnswerResult(q.id, "-", "-", "-", 0, False, False, False, [], [], [], None,
                                time.perf_counter() - t0, error=f"zetaris: {e}")
        except ProviderError as e:
            return AnswerResult(q.id, "-", "-", "-", 0, False, False, False, [], [], [], None,
                                time.perf_counter() - t0, error=f"provider: {e}")
        dt = time.perf_counter() - t0
        plan_online = ans.plan.source == "nightshift"
        writes = ans.completions[1:] if plan_online and ans.completions else list(ans.completions)
        write_reason = next((r for r in ans.fallback_reasons if r.startswith("writer fallback")), None)
        fallback = ans.provider == "offline"
        first_pass = not fallback and len(writes) == 1
        retry_pass = not fallback and len(writes) >= 2
        foreign = re.findall(r"not in the fact sheet \(([^)]*)\)", write_reason or "")
        foreign_list = [f.strip() for f in foreign[0].split(",")] if foreign else []
        res = AnswerResult(
            id=q.id, provider=ans.provider, plan_source=ans.plan.source, coverage=ans.facts.coverage,
            write_attempts=len(writes), first_pass=first_pass, retry_pass=retry_pass, fallback=fallback,
            foreign_figures=foreign_list,
            routed_models=[c.routed_model or "?" for c in ans.completions],
            receipt_ids=[c.receipt_id or "?" for c in ans.completions],
            memory_id=ans.memory.id if ans.memory else None, latency_s=dt,
        )
        if self.judge:
            res.judge, res.judge_receipt = self._judge(render_facts(ans.facts), model_prose(ans.text))
        return res

    def _memory_one(self, agent: Agent, q: Question, first_memory: str | None) -> MemoryResult:
        t0 = time.perf_counter()
        try:
            ans = agent.ask(q.question)
        except (ZetarisError, ProviderError) as e:
            return MemoryResult(q.id, first_memory, [], False, None, time.perf_counter() - t0, error=str(e))
        recalled = [m.id for m in ans.memories_used]
        hit = first_memory is not None and first_memory in recalled
        superseded_ok: bool | None = None
        if ans.memories_used:
            live_first = not ans.memories_used[0].supersededBy
            superseded_ok = live_first or all(m.supersededBy for m in ans.memories_used)
        return MemoryResult(q.id, first_memory, recalled, hit, superseded_ok, time.perf_counter() - t0)

    def _judge(self, sheet: str, candidate: str) -> tuple[dict[str, Any] | None, str | None]:
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"FACT SHEET\n{sheet}\n\nCANDIDATE\n{candidate}"},
        ]
        try:
            comp = self.judge_provider.complete(messages, json_mode=True, max_tokens=400)
            data = json.loads(comp.text)
            if not isinstance(data, dict):
                return None, comp.receipt_id
            return data, comp.receipt_id
        except (ProviderError, ValueError):
            return None, None

    # -- summary -----------------------------------------------------------------

    def _summarise(self) -> None:
        s: dict[str, Any] = {}
        if self.report.plan:
            p = self.report.plan
            by_route: dict[str, list[bool]] = {}
            for r in p:
                by_route.setdefault(r.routed_model or r.source, []).append(r.ok)
            s["plan"] = {
                "runs": len(p),
                "exact": sum(r.ok for r in p),
                "intent": sum(r.intent_ok for r in p),
                "state": sum(r.state_ok for r in p),
                "window": sum(r.window_ok for r in p),
                "pathogen": sum(r.pathogen_ok for r in p),
                "offline_fallbacks": sum(r.source == "offline" for r in p),
                "median_latency_s": round(statistics.median(r.latency_s for r in p), 2),
                "by_route": {k: f"{sum(v)}/{len(v)}" for k, v in by_route.items()},
            }
        if self.report.answer:
            a = [r for r in self.report.answer if not r.error]
            judged = [r for r in a if r.judge and isinstance(r.judge.get("fidelity"), (int, float))]
            s["answer"] = {
                "runs": len(self.report.answer),
                "errors": sum(bool(r.error) for r in self.report.answer),
                "first_pass": sum(r.first_pass for r in a),
                "retry_pass": sum(r.retry_pass for r in a),
                "fallback": sum(r.fallback for r in a),
                "coverage": {c: sum(r.coverage == c for r in a) for c in ("full", "partial", "empty")},
                "median_latency_s": round(statistics.median(r.latency_s for r in a), 2) if a else None,
                "judge_mean_fidelity": round(statistics.mean(r.judge["fidelity"] for r in judged), 2) if judged else None,
                "judge_mean_clarity": round(statistics.mean(r.judge["clarity"] for r in judged if isinstance(r.judge.get("clarity"), (int, float))), 2) if judged else None,
                "judge_accept": sum(r.judge.get("verdict") == "accept" for r in judged),
                "judged": len(judged),
            }
        if self.report.memory:
            m = [r for r in self.report.memory if not r.error]
            s["memory"] = {
                "runs": len(self.report.memory),
                "hits": sum(r.hit for r in m),
                "superseded_outranked": sum(bool(r.superseded_outranked) for r in m if r.superseded_outranked is not None),
                "median_latency_s": round(statistics.median(r.latency_s for r in m), 2) if m else None,
            }
        self.report.summary = s


def model_prose(answer_text: str) -> str:
    """The model's own sentences: drop the [offline] prefix and the appended
    prior-finding sentence, which carries figures from another window."""
    text = answer_text.removeprefix("[offline] ")
    cut = text.find(" Earlier finding on record (")
    return text[:cut] if cut != -1 else text


def _fmt_exp(exp: tuple[date, date] | None) -> str:
    return "any" if exp is None else f"{exp[0]}..{exp[1]}"


def print_summary(report: Report, log=print) -> None:
    s = report.summary
    log("\n=== summary ===")
    if "plan" in s:
        p = s["plan"]
        log(f"plan:    exact {p['exact']}/{p['runs']}  intent {p['intent']}  state {p['state']}  window {p['window']}  pathogen {p.get('pathogen', '-')}  "
            f"offline {p['offline_fallbacks']}  median {p['median_latency_s']}s")
        for route, score in p["by_route"].items():
            log(f"         {route}: {score}")
    if "answer" in s:
        a = s["answer"]
        log(f"answer:  first-pass {a['first_pass']}/{a['runs'] - a['errors']}  retry {a['retry_pass']}  fallback {a['fallback']}  "
            f"errors {a['errors']}  coverage {a['coverage']}  median {a['median_latency_s']}s")
        if a["judged"]:
            log(f"         judge: fidelity {a['judge_mean_fidelity']}/10  clarity {a['judge_mean_clarity']}/10  "
                f"accept {a['judge_accept']}/{a['judged']}")
    if "memory" in s:
        m = s["memory"]
        log(f"memory:  recall hits {m['hits']}/{m['runs']}  superseded outranked {m['superseded_outranked']}  median {m['median_latency_s']}s")
    for layer, why in report.skipped.items():
        log(f"skipped: {layer}: {why[:120]}")
