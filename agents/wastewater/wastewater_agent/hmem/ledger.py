"""Append-only JSONL trust ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .record import now_iso

ACTIONS = frozenset(
    {
        "create",
        "read",
        "update",
        "delete",
        "promote",
        "demote",
        "archive",
        "restore",
        "feedback",
        "conflict_detected",
        "conflict_resolved",
        "supersede",
        "sleep_consolidate",
        "sleep_archive",
        "sleep_synthesize",
        "decay",
        "backup",
    }
)
assert len(ACTIONS) == 17


class LedgerError(ValueError):
    pass


class TrustLedgerService:
    def __init__(self, path: Path) -> None:
        self.path = path

    def log(
        self,
        memory_id: str,
        action: str,
        actor: str = "wastewater-agent",
        *,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action not in ACTIONS:
            raise LedgerError(f"unknown ledger action {action!r}")
        entry: dict[str, Any] = {
            "memoryId": memory_id,
            "action": action,
            "actor": actor,
            "timestamp": now_iso(),
        }
        if previous_state is not None:
            entry["previousState"] = previous_state
        if new_state is not None:
            entry["newState"] = new_state
        entry["details"] = details or {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self, memory_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if memory_id is None or entry.get("memoryId") == memory_id:
                out.append(entry)
        return out
