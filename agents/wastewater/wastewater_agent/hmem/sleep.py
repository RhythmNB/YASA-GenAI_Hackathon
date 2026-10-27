"""Sleep cycle: consolidate idle short-term/working records to long_term,
archive stale unreferenced ones. Backup first; restorable."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ledger import TrustLedgerService
from .record import MemoryRecord, now_iso, parse_iso
from .store import MemoryStoreService

CONSOLIDATE_IDLE_DAYS = 7
ARCHIVE_AGE_DAYS = 30
ARCHIVE_MAX_ACCESS = 2


class SleepCycleService:
    def __init__(self, store: MemoryStoreService, ledger: TrustLedgerService, directory: Path) -> None:
        self.store = store
        self.ledger = ledger
        self.backups = directory / "backups"

    # -- preview --------------------------------------------------------------

    def preview(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        referenced: set[str] = set()
        for r in self.store.all():
            referenced.update(r.relatedTo)
            referenced.update(r.derivedFrom)
            if r.supersedes:
                referenced.add(r.supersedes)
        to_consolidate: list[str] = []
        to_archive: list[str] = []
        for r in self.store.all(("short_term", "working", "long_term")):
            age = _days(parse_iso(r.createdAt), now)
            if age is None or age < ARCHIVE_AGE_DAYS or r.accessCount > ARCHIVE_MAX_ACCESS:
                continue
            if r.id in referenced or r.supersedes or r.derivedFrom:
                continue
            to_archive.append(r.id)
        # A record that qualifies for archiving is stale, not worth promoting.
        for r in self.store.all(("short_term", "working")):
            idle = _days(parse_iso(r.lastAccessed), now)
            if idle is not None and idle >= CONSOLIDATE_IDLE_DAYS and r.id not in to_archive:
                to_consolidate.append(r.id)
        return {
            "asOf": now.replace(microsecond=0).isoformat(),
            "toConsolidate": to_consolidate,
            "toArchive": to_archive,
            "toSynthesize": [],
        }

    # -- execute --------------------------------------------------------------

    def execute(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        plan = self.preview(now)
        backup_id = self.backup()
        for mid in plan["toConsolidate"]:
            rec = self.store.get(mid)
            if rec is None:
                continue
            before = rec.snapshot()
            self.store.set_layer(rec, "long_term")
            self.ledger.log(mid, "sleep_consolidate", previous_state=before, new_state=rec.snapshot(),
                            details={"backupId": backup_id})
        for mid in plan["toArchive"]:
            rec = self.store.get(mid)
            if rec is None:
                continue
            before = rec.snapshot()
            self.store.set_layer(rec, "archived")
            self.ledger.log(mid, "sleep_archive", previous_state=before, new_state=rec.snapshot(),
                            details={"backupId": backup_id})
        self.store.save()
        report = {**plan, "backupId": backup_id, "executedAt": now_iso(),
                  "consolidated": len(plan["toConsolidate"]), "archived": len(plan["toArchive"])}
        (self.backups / f"{backup_id}.report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return report

    def backup(self) -> str:
        self.backups.mkdir(parents=True, exist_ok=True)
        backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload = {"backupId": backup_id, "createdAt": now_iso(), "tiers": self.store.snapshot_all()}
        (self.backups / f"{backup_id}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        self.ledger.log("*", "backup", details={"backupId": backup_id, "records": len(self.store.records)})
        return backup_id

    def list_backups(self) -> list[str]:
        if not self.backups.is_dir():
            return []
        return sorted(p.stem for p in self.backups.glob("*.json") if not p.name.endswith(".report.json"))

    def restore(self, backup_id: str) -> dict[str, Any]:
        path = self.backups / f"{backup_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"no backup {backup_id!r}; available: {', '.join(self.list_backups()) or 'none'}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.store.replace_all(payload["tiers"])
        self.store.save()
        self.ledger.log("*", "restore", details={"backupId": backup_id, "records": len(self.store.records)})
        return {"backupId": backup_id, "records": len(self.store.records), "counts": self.store.counts()}


def _days(when: datetime | None, now: datetime) -> float | None:
    if when is None:
        return None
    return (now - when).total_seconds() / 86400.0
