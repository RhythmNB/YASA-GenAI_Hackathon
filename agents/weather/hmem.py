"""H-MEM (Meterless Agent Engine): shared, tiered memory for the agents.

Minimum implementation from the Meterless guide:
  MemoryStoreService      saves memories in short / working / long tiers, with
                          source, confidence, entities, tags and replacement lineage
  MemoryRetrievalService  scores memories by keyword, entity, tag, recency,
                          tier and confidence, and returns the top N as a
                          structured context block for an agent's prompt

Storage is an append-only JSONL event log (memory/hmem.jsonl) replayed on load,
plus a trust ledger (memory/ledger.jsonl) recording every mutation.
Dreaming/sleep are intentionally not implemented yet.
"""
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TIERS = ("short", "working", "long")
# Hours for a memory's recency score to halve, per tier.
HALF_LIFE_H = {"short": 12, "working": 72, "long": 24 * 90}
TIER_WEIGHT = {"short": 0.6, "working": 0.8, "long": 1.0}
WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "with", "at", "my"}


def _now():
    return datetime.now(timezone.utc)


def _tokens(text):
    return {w for w in WORD.findall(str(text).lower()) if w not in STOP}


def _norm(items):
    return {str(i).strip().lower() for i in (items or []) if i}


@dataclass
class MemoryRecord:
    content: str
    tier: str = "working"
    source: str = "unknown"
    confidence: float = 0.8
    entities: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    key: str = None
    id: str = field(default_factory=lambda: "mem_" + uuid.uuid4().hex[:10])
    created_at: str = field(default_factory=lambda: _now().isoformat(timespec="seconds"))
    supersedes: str = None
    superseded_by: str = None


class MemoryStoreService:
    def __init__(self, path=None, ledger_path=None, tracer=None):
        self.path = Path(path) if path else HERE / "memory" / "hmem.jsonl"
        self.ledger_path = Path(ledger_path) if ledger_path else self.path.with_name("ledger.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.tracer = tracer
        self.records = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev["op"] == "add":
                rec = MemoryRecord(**ev["record"])
                self.records[rec.id] = rec
            elif ev["op"] == "supersede" and ev["id"] in self.records:
                self.records[ev["id"]].superseded_by = ev["by"]

    def _append(self, ev):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now().isoformat(timespec="seconds"), **ev}) + "\n")

    def active(self):
        return [r for r in self.records.values() if not r.superseded_by]

    def add(self, content, tier="working", source="unknown", confidence=0.8,
            entities=None, tags=None, key=None):
        """Save a memory. A key (e.g. 'weather:NYC:Saturday') makes the new
        memory replace the previous active one with the same key."""
        if tier not in TIERS:
            raise ValueError(f"tier must be one of {TIERS}")
        old = None
        if key:
            old = next((r for r in self.active() if r.key == key), None)
            if old and old.content == content:
                return old  # nothing changed; keep store idempotent
        rec = MemoryRecord(
            content=content, tier=tier, source=source,
            confidence=max(0.0, min(1.0, float(confidence))),
            entities=list(entities or []), tags=list(tags or []), key=key,
            supersedes=old.id if old else None,
        )
        self.records[rec.id] = rec
        self._append({"op": "add", "record": asdict(rec)})
        if old:
            old.superseded_by = rec.id
            self._append({"op": "supersede", "id": old.id, "by": rec.id})
        if self.tracer:
            self.tracer.event("hmem_write", id=rec.id, tier=tier, key=key,
                              supersedes=rec.supersedes, source=source, content=content)
        return rec


class MemoryRetrievalService:
    def __init__(self, store, tracer=None):
        self.store = store
        self.tracer = tracer

    def score(self, rec, q_tokens, q_entities, q_tags, now=None):
        now = now or _now()
        r_tokens = _tokens(rec.content) | _tokens(" ".join(rec.tags))
        keyword = len(q_tokens & r_tokens) / len(q_tokens) if q_tokens else 0.0
        entity = len(q_entities & _norm(rec.entities)) / len(q_entities) if q_entities else 0.0
        tag = len(q_tags & _norm(rec.tags)) / len(q_tags) if q_tags else 0.0
        age_h = max(0.0, (now - datetime.fromisoformat(rec.created_at)).total_seconds() / 3600)
        recency = math.pow(0.5, age_h / HALF_LIFE_H[rec.tier])
        return (0.35 * keyword + 0.30 * entity + 0.10 * tag + 0.10 * recency
                + 0.05 * TIER_WEIGHT[rec.tier] + 0.10 * rec.confidence)

    def retrieve(self, query, entities=None, tags=None, top_n=5, min_score=0.2, agent="unknown"):
        q_tokens, q_entities, q_tags = _tokens(query), _norm(entities), _norm(tags)
        scored = sorted(
            ((self.score(r, q_tokens, q_entities, q_tags), r) for r in self.store.active()),
            key=lambda x: x[0], reverse=True,
        )
        hits = [(round(s, 3), r) for s, r in scored if s >= min_score][:top_n]
        if self.tracer:
            self.tracer.event("hmem_retrieve", agent=agent, query=query,
                              entities=sorted(q_entities), tags=sorted(q_tags),
                              hits=[{"id": r.id, "score": s, "tier": r.tier, "content": r.content}
                                    for s, r in hits])
        return hits

    @staticmethod
    def format_context(hits):
        if not hits:
            return "MEMORY CONTEXT: (none)"
        lines = ["MEMORY CONTEXT (from H-MEM, most relevant first):"]
        for s, r in hits:
            lines.append(f"- [{r.tier}, confidence {r.confidence:.2f}, source {r.source}] {r.content}")
        return "\n".join(lines)
