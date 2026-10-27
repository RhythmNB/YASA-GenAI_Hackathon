"""JSONL tracing: one line per event in logs/run_<id>.jsonl, so judges can see
how the agents reached their output (memory lookups, tool calls, model calls,
hand-offs, evaluator verdicts)."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Tracer:
    def __init__(self, run_id=None, log_dir=None):
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        self.log_dir = Path(log_dir) if log_dir else HERE / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"run_{self.run_id}.jsonl"

    def event(self, kind, **data):
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "kind": kind,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
        return line
