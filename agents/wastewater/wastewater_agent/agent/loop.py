"""ask(question) orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from collections.abc import Callable
from typing import Any

from .. import pathogens
from ..config import Settings
from ..hmem import HMem
from ..hmem.record import MemoryRecord
from ..llm import Completion, NightshiftProvider, OfflineProvider, ProviderUnauthorized
from ..states import state_name
from ..zetaris import JdbcClient
from . import evaluator, planner, windows, writer
from .executor import Executor
from .evaluator import FactSheet
from .planner import Plan

DOMAIN = "wastewater"


@dataclass
class Answer:
    text: str
    plan: Plan
    facts: FactSheet
    statements: list[str]
    memories_used: list[MemoryRecord]
    memory: MemoryRecord | None
    conflicts: list[dict[str, Any]]
    completions: list[Completion]
    provider: str  # nightshift | offline
    fallback_reasons: list[str] = field(default_factory=list)
    retrieval_reason: str = ""


class Agent:
    def __init__(
        self,
        settings: Settings,
        *,
        client: JdbcClient | None = None,
        hmem: HMem | None = None,
        provider: NightshiftProvider | None = None,
        today: date | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or JdbcClient(settings)
        self.hmem = hmem or HMem(settings.hmem_dir)
        self.nightshift = provider or NightshiftProvider(settings.nightshift_base_url, settings.nightshift_token, models=settings.nightshift_models)
        self.offline = OfflineProvider()
        self.today = today or date.today()

    def _select_provider(self) -> tuple[NightshiftProvider | None, str | None]:
        state, _ = self.nightshift.readiness()
        if state == "online":
            return self.nightshift, None
        if state == "unauthorized":
            raise ProviderUnauthorized(
                f"Nightshift rejected the token ({self.settings.nightshift_token_source}); check the token file"
            )
        return None, "nightshift offline (GET /v1/models failed)"

    def ask(self, question: str, county: str | None = None, pathogen: str | None = None,
            progress: Callable[[dict[str, Any]], None] | None = None) -> Answer:
        """`county` is an optional county name (any common form) inside the question's state,
        e.g. from a geocoded city; it narrows every query to sites serving that county.
        `pathogen` is a registry key ('sars-cov-2', 'flu-a'); when absent the question's words decide.
        `progress`, when given, receives one dict per stage ({"stage", "state", ...}) as the
        question is processed, including every Nightshift route attempt with its model."""
        self.nightshift.on_event = progress
        try:
            return self._ask(question, county, pathogen, progress or (lambda e: None))
        finally:
            self.nightshift.on_event = None

    def _ask(self, question: str, county: str | None, pathogen: str | None,
             emit: Callable[[dict[str, Any]], None]) -> Answer:
        fallbacks: list[str] = []
        provider, reason = self._select_provider()
        if reason:
            fallbacks.append(reason)

        hint = windows.resolve(question, self.today)
        emit({"stage": "plan", "state": "start"})
        plan, plan_completion, plan_reason = planner.plan(question, hint, self.today, provider, self.offline,
                                                         county=county, pathogen=pathogen)
        if plan_reason:
            fallbacks.append(plan_reason)
        emit({"stage": "plan", "state": "done", "source": plan.source,
              "model": plan_completion.routed_model if plan_completion is not None else None,
              "fallback": plan_reason, "pathogen": plan.pathogen, "state_code": plan.state, "county": plan.county})

        recalled = self.hmem.recall(
            question,
            entities=[e for e in (plan.pathogen, plan.state or "us", plan.county, plan.window.start.isoformat(), plan.window.end.isoformat()) if e],
            tags=[plan.pathogen, plan.intent, plan.state or "us"] + ([plan.county.lower()] if plan.county else []),
            domain=DOMAIN,
        )
        # Only findings about the same virus may be quoted back. Records written before the
        # pathogen tag existed are SARS-CoV-2 findings.
        known = set(pathogens.PATHOGENS)
        same_virus = [m for m in recalled.memories
                      if (next((t for t in m.tags if t in known), pathogens.DEFAULT_KEY)) == plan.pathogen]
        recalled.memories = same_virus
        memory_views = [
            {"id": m.id, "content": m.content, "learnedAt": m.provenance.get("learnedAt"),
             "confidence": m.confidence, "superseded": bool(m.supersededBy)}
            for m in same_virus
        ]
        emit({"stage": "recall", "state": "done", "count": len(same_virus)})

        emit({"stage": "query", "state": "start"})
        executor = Executor(self.client)
        results = executor.run(plan)
        facts = evaluator.evaluate(plan, results, fetch_fallback=executor.summary)
        statements = list(executor.statements)
        emit({"stage": "query", "state": "done", "statements": len(statements), "coverage": facts.coverage,
              "samples": facts.samples})

        emit({"stage": "write", "state": "start"})
        text, write_completions, write_reason = writer.write(facts, memory_views, provider, self.offline)
        if write_reason:
            fallbacks.append(write_reason)
        emit({"stage": "write", "state": "done", "attempts": len(write_completions), "fallback": write_reason,
              "model": write_completions[-1].routed_model if write_completions and write_reason is None else None})

        record, conflicts = self.hmem.remember(**memory_fields(facts, plan, statements))
        emit({"stage": "memory", "state": "done", "id": record.id, "conflicts": len(conflicts)})

        completions = ([plan_completion] if plan_completion is not None else []) + write_completions
        # The label describes who wrote the answer prose; notes list any fallbacks.
        provider_name = "nightshift" if provider is not None and write_reason is None else "offline"
        if provider_name == "offline":
            text = "[offline] " + text
        return Answer(
            text=text,
            plan=plan,
            facts=facts,
            statements=statements,
            memories_used=recalled.memories,
            memory=record,
            conflicts=[c.to_dict() for c in conflicts],
            completions=completions,
            provider=provider_name,
            fallback_reasons=fallbacks,
            retrieval_reason=recalled.retrievalReason,
        )

    def close(self) -> None:
        self.client.close()


def memory_fields(facts: FactSheet, plan: Plan, statements: list[str]) -> dict[str, Any]:
    region = plan.state or "us"
    w = plan.window
    label = hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()[:16]
    content = summarise(facts)
    entities = [plan.pathogen, region] + ([plan.county] if plan.county else []) + [w.start.isoformat(), w.end.isoformat()]
    if facts.fallback_window is not None:
        entities += [facts.fallback_window.start.isoformat(), facts.fallback_window.end.isoformat()]
    metadata: dict[str, Any] = {
        "intent": plan.intent,
        "pathogen": plan.pathogen,
        "state": plan.state,
        "county": plan.county,
        "windowStart": w.start.isoformat(),
        "windowEnd": w.end.isoformat(),
        "samples": facts.samples,
        "positives": facts.positives,
        "positiveShare": facts.positive_share,
        "sites": facts.sites,
        "meanConc": facts.mean_conc,
        "coverage": facts.coverage,
        "latestSampleDate": facts.latest_sample_date.isoformat() if facts.latest_sample_date else None,
        "direction": facts.direction,
        "deltaShare": facts.delta_share,
        "fallbackWindow": facts.fallback_window.to_dict() if facts.fallback_window else None,
        "fallbackSamples": facts.fallback_samples,
        "fallbackPositives": facts.fallback_positives,
    }
    return {
        "content": content,
        "tags": [plan.pathogen, plan.intent, region] + ([plan.county.lower()] if plan.county else []),
        "entities": entities,
        "metadata": metadata,
        "label": label,
        "confidence": 0.9 if facts.coverage == "full" else 0.7,
    }


def summarise(facts: FactSheet) -> str:
    where = facts.region or state_name(facts.state)
    w = facts.window
    if facts.coverage == "empty":
        s = f"No {facts.pathogen_name} wastewater samples for {where} {w.start}..{w.end} (latest sample {facts.latest_sample_date})"
        if facts.fallback_window and facts.fallback_samples:
            fw = facts.fallback_window
            s += (f"; most recent 7-day window {fw.start}..{fw.end}: {facts.fallback_positives}/{facts.fallback_samples} "
                  f"positive ({_pct(facts.fallback_positive_share)}), {facts.fallback_sites} sites")
        return s + "."
    s = (f"{facts.pathogen_name} {'detected' if facts.positives else 'not detected'} in {where} {w.start}..{w.end}: "
         f"{facts.positives}/{facts.samples} positive ({_pct(facts.positive_share)}), {facts.sites} sites")
    if facts.mean_conc is not None:
        s += f", mean conc {facts.mean_conc:,.0f}"
    if facts.coverage == "partial":
        s += f" (partial coverage, latest sample {facts.latest_sample_date})"
    if facts.intent == "trend" and facts.direction:
        s += f"; vs preceding window positive share {facts.direction}"
        if facts.delta_share is not None:
            s += f" ({facts.delta_share:+.1f} pp)"
    return s + "."


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share * 100:.1f}%"
