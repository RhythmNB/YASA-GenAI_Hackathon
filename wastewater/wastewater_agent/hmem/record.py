"""H-MEM memory record (camelCase field names as in the Meterless spec)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

LAYERS = ("short_term", "working", "long_term", "archived")
RETRIEVABLE_LAYERS = ("short_term", "working", "long_term")
MAX_ENTITIES = 10
MAX_RELATED = 5


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_id() -> str:
    return "mem_" + uuid.uuid4().hex[:12]


class RecordError(ValueError):
    pass


@dataclass
class MemoryRecord:
    content: str
    source: str
    provenance: dict[str, Any]
    id: str = field(default_factory=new_id)
    layer: str = "working"
    type: str = "factual"
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    domain: str = ""
    namespace: str = ""
    confidence: float = 0.5
    createdAt: str = field(default_factory=now_iso)
    updatedAt: str = field(default_factory=now_iso)
    lastAccessed: str = field(default_factory=now_iso)
    accessCount: int = 0
    relatedTo: list[str] = field(default_factory=list)
    derivedFrom: list[str] = field(default_factory=list)
    supersedes: str | None = None
    supersededBy: str | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- validation ----------------------------------------------------------

    def validate(self) -> None:
        if not self.id:
            raise RecordError("id is required")
        if not isinstance(self.content, str) or not self.content.strip():
            raise RecordError("content is required")
        if self.layer not in LAYERS:
            raise RecordError(f"layer must be one of {LAYERS}, got {self.layer!r}")
        if not self.source:
            raise RecordError("source is required")
        if not isinstance(self.provenance, dict) or not self.provenance.get("origin") or not self.provenance.get("learnedAt"):
            raise RecordError("provenance.origin and provenance.learnedAt are required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise RecordError("confidence must be in [0, 1]")
        if len(self.entities) > MAX_ENTITIES:
            raise RecordError(f"entities capped at {MAX_ENTITIES}")
        if len(self.relatedTo) > MAX_RELATED:
            raise RecordError(f"relatedTo capped at {MAX_RELATED}")
        for name in ("tags", "entities", "relatedTo", "derivedFrom"):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise RecordError(f"{name} must be a list of strings")

    # -- (de)serialisation ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        for name in ("tags", "entities", "relatedTo", "derivedFrom"):
            clean.setdefault(name, [])
            clean[name] = list(clean[name] or [])
        clean.setdefault("metadata", {})
        clean.setdefault("provenance", {})
        record = cls(**clean)
        return record

    def touch(self, when: str | None = None) -> None:
        self.lastAccessed = when or now_iso()
        self.accessCount += 1

    def snapshot(self) -> dict[str, Any]:
        """Small state view for ledger previousState/newState."""
        return {
            "layer": self.layer,
            "confidence": round(float(self.confidence), 4),
            "accessCount": self.accessCount,
            "tags": list(self.tags),
            "supersededBy": self.supersededBy,
        }
