"""Memory tiers: short_term in memory; working, long_term and archived as JSON.

Load hydrates the files, merges with the session, de-duplicates by id,
backfills missing embeddings and applies forgetting-curve decay to records
that are not long-term (confidence x e^(-days/30), floored at 0.1). Decay
never deletes.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .embed import embed
from .record import LAYERS, MemoryRecord, now_iso, parse_iso

FILE_LAYERS = ("working", "long_term", "archived")
DECAY_DAYS = 30.0
DECAY_FLOOR = 0.1
EMBEDDING_VERSION = "content+tags+entities/v1"


def embedding_text(rec: MemoryRecord) -> str:
    """Text that is embedded and keyword-matched: content plus tags and
    entities, so a short question naming a state and dates lands on the
    record for that state and window."""
    return " ".join([rec.content, *rec.tags, *rec.entities])


def embed_record(rec: MemoryRecord) -> None:
    rec.embedding = embed(embedding_text(rec))
    rec.metadata["embeddingVersion"] = EMBEDDING_VERSION


class MemoryStoreService:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.records: dict[str, MemoryRecord] = {}

    def _path(self, layer: str) -> Path:
        return self.dir / f"{layer}.json"

    # -- load / save -----------------------------------------------------------

    def load(self, now: datetime | None = None) -> dict[str, int]:
        """Hydrate from disk, merge with the session, decay. Returns stats."""
        now = now or datetime.now(timezone.utc)
        hydrated = 0
        backfilled = 0
        decayed: list[tuple[str, float, float]] = []
        for layer in FILE_LAYERS:
            path = self._path(layer)
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for raw in data.get("records", []):
                try:
                    rec = MemoryRecord.from_dict(raw)
                    rec.validate()
                except Exception:
                    continue
                existing = self.records.get(rec.id)
                if existing is not None and (existing.updatedAt or "") >= (rec.updatedAt or ""):
                    continue  # de-duplicate by id, keep the newest
                self.records[rec.id] = rec
                hydrated += 1
        for rec in self.records.values():
            if not rec.embedding or rec.metadata.get("embeddingVersion") != EMBEDDING_VERSION:
                embed_record(rec)
                backfilled += 1
            change = self._decay(rec, now)
            if change:
                decayed.append((rec.id, *change))
        self._decayed = decayed
        return {"hydrated": hydrated, "backfilled": backfilled, "decayed": len(decayed)}

    def _decay(self, rec: MemoryRecord, now: datetime) -> tuple[float, float] | None:
        if rec.layer in ("long_term", "archived"):
            return None
        anchor = max(
            [d for d in (parse_iso(rec.lastAccessed), parse_iso(rec.metadata.get("decayedAt"))) if d],
            default=None,
        )
        if anchor is None:
            return None
        days = max(0.0, (now - anchor).total_seconds() / 86400.0)
        if days < 1.0 / 24:
            return None
        before = float(rec.confidence)
        after = max(DECAY_FLOOR, before * math.exp(-days / DECAY_DAYS))
        rec.metadata["decayedAt"] = now.replace(microsecond=0).isoformat()
        if abs(after - before) < 1e-6:
            return None
        rec.confidence = round(after, 4)
        return before, after

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for layer in FILE_LAYERS:
            recs = [r.to_dict() for r in self.records.values() if r.layer == layer]
            payload = {"layer": layer, "savedAt": now_iso(), "records": recs}
            self._path(layer).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    # -- access ----------------------------------------------------------------

    def add(self, rec: MemoryRecord) -> MemoryRecord:
        rec.validate()
        if not rec.embedding:
            embed_record(rec)
        self.records[rec.id] = rec
        return rec

    def get(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def all(self, layers: Iterable[str] | None = None) -> list[MemoryRecord]:
        wanted = set(layers) if layers else set(LAYERS)
        return [r for r in self.records.values() if r.layer in wanted]

    def set_layer(self, rec: MemoryRecord, layer: str) -> None:
        if layer not in LAYERS:
            raise ValueError(f"unknown layer {layer!r}")
        rec.layer = layer
        rec.updatedAt = now_iso()

    def counts(self) -> dict[str, int]:
        out = {layer: 0 for layer in LAYERS}
        for r in self.records.values():
            out[r.layer] = out.get(r.layer, 0) + 1
        return out

    def snapshot_all(self) -> dict:
        return {layer: [r.to_dict() for r in self.records.values() if r.layer == layer] for layer in LAYERS}

    def replace_all(self, snapshot: dict) -> None:
        self.records = {}
        for layer, recs in snapshot.items():
            for raw in recs:
                rec = MemoryRecord.from_dict(raw)
                rec.layer = layer
                self.records[rec.id] = rec
