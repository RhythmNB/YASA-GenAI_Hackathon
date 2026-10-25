"""Conflict detection: same entity set and domain, divergent figures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ledger import TrustLedgerService
from .record import MemoryRecord, now_iso

AUTO_RESOLVE = 0.70
SHARED_ENTITY_CONFIDENCE = 0.8
COMPARED_FIELDS = ("positives", "samples")


@dataclass
class Conflict:
    existing: MemoryRecord
    incoming: MemoryRecord
    confidence: float
    reason: str
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "existingId": self.existing.id,
            "incomingId": self.incoming.id,
            "confidence": self.confidence,
            "reason": self.reason,
            "resolved": self.resolved,
        }


class ConflictDetectionService:
    def __init__(self, ledger: TrustLedgerService) -> None:
        self.ledger = ledger

    def detect(self, incoming: MemoryRecord, existing: list[MemoryRecord]) -> list[Conflict]:
        out: list[Conflict] = []
        in_entities = set(incoming.entities)
        in_meta = incoming.metadata or {}
        for rec in existing:
            if rec.id == incoming.id or rec.supersededBy:
                continue
            if rec.domain != incoming.domain or set(rec.entities) != in_entities:
                continue
            meta = rec.metadata or {}
            diffs = [
                f"{f}: {meta.get(f)} -> {in_meta.get(f)}"
                for f in COMPARED_FIELDS
                if f in meta and f in in_meta and meta.get(f) != in_meta.get(f)
            ]
            if not diffs:
                continue
            out.append(
                Conflict(rec, incoming, SHARED_ENTITY_CONFIDENCE,
                         "shared entities and domain; " + ", ".join(diffs))
            )
        return out

    def resolve(self, conflicts: list[Conflict]) -> list[Conflict]:
        for c in conflicts:
            self.ledger.log(c.incoming.id, "conflict_detected",
                            details={"with": c.existing.id, "confidence": c.confidence, "reason": c.reason})
            if c.confidence < AUTO_RESOLVE:
                continue
            older, newer = c.existing, c.incoming
            before = older.snapshot()
            older.supersededBy = newer.id
            older.updatedAt = now_iso()
            newer.supersedes = older.id
            c.resolved = True
            self.ledger.log(older.id, "supersede", previous_state=before, new_state=older.snapshot(),
                            details={"by": newer.id})
            self.ledger.log(newer.id, "conflict_resolved",
                            details={"supersedes": older.id, "strategy": "keep both; older marked supersededBy"})
        return conflicts
