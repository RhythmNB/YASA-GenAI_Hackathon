"""HMem facade used by the agent and the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .conflict import Conflict, ConflictDetectionService
from .ledger import TrustLedgerService
from .record import MemoryRecord, now_iso
from .retrieval import MemoryRetrievalService, RetrievalResult
from .sleep import SleepCycleService
from .store import MemoryStoreService

FEEDBACK = {
    "helpful": {"confidence": +0.05, "access": 1},
    "not_helpful": {"confidence": -0.03, "access": 0},
    "wrong": {"confidence": -0.20, "access": 0, "tag": "review"},
}


class HMem:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.store = MemoryStoreService(directory)
        self.ledger = TrustLedgerService(directory / "ledger.jsonl")
        self.retrieval = MemoryRetrievalService(self.store, self.ledger)
        self.conflicts = ConflictDetectionService(self.ledger)
        self.sleep = SleepCycleService(self.store, self.ledger, directory)
        self.load_stats = self.store.load()
        if self.load_stats.get("decayed"):
            for mid, before, after in getattr(self.store, "_decayed", []):
                self.ledger.log(mid, "decay", previous_state={"confidence": round(before, 4)},
                                new_state={"confidence": round(after, 4)})
        if self.load_stats.get("decayed") or self.load_stats.get("backfilled"):
            self.store.save()

    # -- read ------------------------------------------------------------------

    def recall(self, query: str, *, entities: list[str], tags: list[str], domain: str) -> RetrievalResult:
        result = self.retrieval.recall(query, entities=entities, tags=tags, domain=domain)
        if result.memories:
            self.store.save()
        return result

    def list(self, layer: str | None = None) -> list[MemoryRecord]:
        recs = self.store.all([layer]) if layer else self.store.all()
        return sorted(recs, key=lambda r: r.createdAt, reverse=True)

    def show(self, memory_id: str) -> MemoryRecord | None:
        return self.store.get(memory_id)

    def audit(self, memory_id: str) -> list[dict[str, Any]]:
        return self.ledger.entries(memory_id)

    def counts(self) -> dict[str, int]:
        return self.store.counts()

    # -- write -----------------------------------------------------------------

    def remember(
        self,
        *,
        content: str,
        tags: list[str],
        entities: list[str],
        metadata: dict[str, Any],
        label: str,
        confidence: float,
        domain: str = "wastewater",
        namespace: str = "cdc_nwss",
        source: str = "zetaris",
        type: str = "factual",
        layer: str = "working",
    ) -> tuple[MemoryRecord, list[Conflict]]:
        rec = MemoryRecord(
            content=content,
            source=source,
            provenance={"origin": "tool", "learnedAt": now_iso(), "label": label},
            layer=layer,
            type=type,
            tags=list(tags),
            entities=list(entities)[:10],
            domain=domain,
            namespace=namespace,
            confidence=float(confidence),
            metadata=dict(metadata),
        )
        found = self.conflicts.detect(rec, self.store.all(("short_term", "working", "long_term")))
        self.store.add(rec)
        self.ledger.log(rec.id, "create", new_state=rec.snapshot(),
                        details={"label": label, "entities": rec.entities, "tags": rec.tags})
        resolved = self.conflicts.resolve(found)
        self.store.save()
        return rec, resolved

    def feedback(self, memory_id: str, kind: str) -> MemoryRecord:
        if kind not in FEEDBACK:
            raise ValueError(f"feedback must be one of {sorted(FEEDBACK)}")
        rec = self.store.get(memory_id)
        if rec is None:
            raise KeyError(memory_id)
        rule = FEEDBACK[kind]
        before = rec.snapshot()
        rec.accessCount += rule["access"]
        rec.confidence = round(min(1.0, max(0.0, float(rec.confidence) + rule["confidence"])), 4)
        if rule.get("tag") and rule["tag"] not in rec.tags:
            rec.tags.append(rule["tag"])
        rec.updatedAt = now_iso()
        self.ledger.log(rec.id, "feedback", actor="user", previous_state=before, new_state=rec.snapshot(),
                        details={"kind": kind})
        self.store.save()
        return rec

    # -- sleep -----------------------------------------------------------------

    def sleep_preview(self) -> dict[str, Any]:
        return self.sleep.preview()

    def sleep_execute(self) -> dict[str, Any]:
        return self.sleep.execute()

    def sleep_restore(self, backup_id: str) -> dict[str, Any]:
        return self.sleep.restore(backup_id)
