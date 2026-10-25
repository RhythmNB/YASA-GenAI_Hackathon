"""ask(question) orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

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
        self.nightshift = provider or NightshiftProvider(settings.nightshift_base_url, settings.nightshift_token)
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

    def ask(self, question: str) -> Answer:
        fallbacks: list[str] = []
        provider, reason = self._select_provider()
        if reason:
            fallbacks.append(reason)

        hint = windows.resolve(question, self.today)
        plan, plan_completion, plan_reason = planner.plan(question, hint, self.today, provider, self.offline)
        if plan_reason:
            fallbacks.append(plan_reason)

        recalled = self.hmem.recall(
            question,
            entities=[plan.state or "us", plan.window.start.isoformat(), plan.window.end.isoformat()],
            tags=["sars-cov-2", plan.intent, plan.state or "us"],
            domain=DOMAIN,
        )
        memory_views = [
            {"id": m.id, "content": m.content, "learnedAt": m.provenance.get("learnedAt"),
             "confidence": m.confidence, "superseded": bool(m.supersededBy)}
            for m in recalled.memories
        ]

        executor = Executor(self.client)
        results = executor.run(plan)
        facts = evaluator.evaluate(plan, results, fetch_fallback=executor.summary)
        statements = list(executor.statements)

        text, write_completions, write_reason = writer.write(facts, memory_views, provider, self.offline)
        if write_reason:
            fallbacks.append(write_reason)

        record, conflicts = self.hmem.remember(**memory_fields(facts, plan, statements))

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
    entities = [region, w.start.isoformat(), w.end.isoformat()]
    if facts.fallback_window is not None:
        entities += [facts.fallback_window.start.isoformat(), facts.fallback_window.end.isoformat()]
    metadata: dict[str, Any] = {
        "intent": plan.intent,
        "state": plan.state,
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
        "tags": ["sars-cov-2", plan.intent, region],
        "entities": entities,
        "metadata": metadata,
        "label": label,
        "confidence": 0.9 if facts.coverage == "full" else 0.7,
    }


def summarise(facts: FactSheet) -> str:
    where = state_name(facts.state)
    w = facts.window
    if facts.coverage == "empty":
        s = f"No SARS-CoV-2 wastewater samples for {where} {w.start}..{w.end} (latest sample {facts.latest_sample_date})"
        if facts.fallback_window and facts.fallback_samples:
            fw = facts.fallback_window
            s += (f"; most recent 7-day window {fw.start}..{fw.end}: {facts.fallback_positives}/{facts.fallback_samples} "
                  f"positive ({_pct(facts.fallback_positive_share)}), {facts.fallback_sites} sites")
        return s + "."
    s = (f"SARS-CoV-2 {'detected' if facts.positives else 'not detected'} in {where} {w.start}..{w.end}: "
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
