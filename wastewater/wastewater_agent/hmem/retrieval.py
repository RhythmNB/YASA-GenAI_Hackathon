"""Hybrid retrieval with a relevance gate and a trace.

raw = 0.35*semantic + 0.20*keyword + 0.10*tag + 0.10*domain + 0.15*entity
      + 0.05*layer + 0.05*recency - 0.20*superseded
score = clamp01(raw) * confidence; keep score >= 0.35; top 5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .embed import cosine, embed, jaccard, tokenize, top_tokens
from .ledger import TrustLedgerService
from .record import RETRIEVABLE_LAYERS, MemoryRecord, parse_iso
from .store import MemoryStoreService, embedding_text

GATE = 0.35
TOP_K = 5
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
RECENCY_DAYS = 14.0


@dataclass
class RetrievalResult:
    memories: list[MemoryRecord]
    trace: list[dict[str, Any]]
    retrievalReason: str
    candidates: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class MemoryRetrievalService:
    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService) -> None:
        self.store = store
        self.ledger = ledger

    def recall(
        self,
        query: str,
        *,
        entities: list[str] | None = None,
        tags: list[str] | None = None,
        domain: str | None = None,
        now: datetime | None = None,
        touch: bool = True,
    ) -> RetrievalResult:
        now = now or datetime.now(timezone.utc)
        q_tags = set(tags or [])
        q_entities = set(entities or [])
        q_text = " ".join([query, *sorted(q_entities), *sorted(q_tags)])
        q_vec = embed(q_text)
        q_top = top_tokens(q_text)
        scored: list[tuple[float, dict[str, Any], MemoryRecord]] = []
        candidates = self.store.all(RETRIEVABLE_LAYERS)
        for rec in candidates:
            semantic = max(0.0, cosine(q_vec, rec.embedding or embed(embedding_text(rec))))
            keyword = jaccard(q_top, set(tokenize(embedding_text(rec))))
            tag = (len(q_tags & set(rec.tags)) / len(q_tags)) if q_tags else 0.0
            dom = 1.0 if domain and rec.domain == domain else 0.0
            entity = (len(q_entities & set(rec.entities)) / len(q_entities)) if q_entities else 0.0
            layer = LAYER_WEIGHT.get(rec.layer, 0.6)
            last = parse_iso(rec.lastAccessed) or now
            days = max(0.0, (now - last).total_seconds() / 86400.0)
            recency = math.exp(-days / RECENCY_DAYS)
            superseded = 1.0 if rec.supersededBy else 0.0
            raw = (
                0.35 * semantic
                + 0.20 * keyword
                + 0.10 * tag
                + 0.10 * dom
                + 0.15 * entity
                + 0.05 * layer
                + 0.05 * recency
                - 0.20 * superseded
            )
            score = min(1.0, max(0.0, raw)) * float(rec.confidence)
            parts = {
                "memoryId": rec.id,
                "score": round(score, 4),
                "raw": round(raw, 4),
                "semantic": round(semantic, 3),
                "keyword": round(keyword, 3),
                "tag": round(tag, 3),
                "domain": dom,
                "entity": round(entity, 3),
                "layer": layer,
                "recency": round(recency, 3),
                "superseded": superseded,
                "confidence": round(float(rec.confidence), 3),
                "kept": score >= GATE,
            }
            scored.append((score, parts, rec))
        scored.sort(key=lambda t: t[0], reverse=True)
        kept = [(s, p, r) for s, p, r in scored if s >= GATE][:TOP_K]
        trace = [p for _, p, _ in scored[: max(TOP_K, len(kept))]]
        reason = (
            f"{len(candidates)} candidate(s) scored; {len(kept)} passed the {GATE} gate (top {TOP_K}); "
            f"query entities={sorted(q_entities)} tags={sorted(q_tags)} domain={domain}"
        )
        memories: list[MemoryRecord] = []
        for score, parts, rec in kept:
            if touch:
                before = rec.snapshot()
                rec.touch(now.replace(microsecond=0).isoformat())
                self.ledger.log(rec.id, "read", previous_state=before, new_state=rec.snapshot(),
                                details={"query": query, "score": parts["score"]})
            memories.append(rec)
        return RetrievalResult(memories=memories, trace=trace, retrievalReason=reason, candidates=len(candidates))
