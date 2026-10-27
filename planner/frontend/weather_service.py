"""Keeps the weather service available for the planner server.

The weather agent runs as its own program (its own venv, its own .env) on port
8770. The planner server starts it when nothing answers there, checks again
before each plan and restarts it if it has died, and stops it on exit, but only
a process it started itself: a weather service someone runs by hand is reused
and left alone.

Its output goes to agents/weather/logs/service.log (git-ignored)."""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO = Path(__file__).resolve().parent.parent.parent
WEATHER_DIR = REPO / "agents" / "weather"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
START_TIMEOUT_S = 30.0


def _venv_python() -> Path | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = WEATHER_DIR / ".venv" / rel
        if p.is_file():
            return p
    return None


class WeatherSupervisor:
    def __init__(self, url: str | None = None, enabled: bool = True) -> None:
        self.url = (url or os.environ.get("WEATHER_SERVICE_URL") or "http://127.0.0.1:8770").rstrip("/")
        parsed = urlparse(self.url)
        self.port = parsed.port or 8770
        # Only a weather service on this machine can be started from here.
        self.enabled = enabled and (parsed.hostname or "") in LOCAL_HOSTS
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._log = None
        self._http = httpx.Client()  # one client: building one per check reloads the certificate store
        atexit.register(self.stop)

    def alive(self, timeout: float = 1.5) -> bool:
        try:
            return self._http.get(f"{self.url}/api/status", timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    def ensure(self) -> str:
        """Make sure the service answers. Returns what happened, for the server's log."""
        if self.alive():
            return "running"
        if not self.enabled:
            return "not running (auto-start is off or the URL is not local)"
        with self._lock:
            if self.alive():
                return "running"
            py = _venv_python()
            if py is None:
                return f"not running: no venv at {WEATHER_DIR / '.venv'} (see agents/weather/SETUP-NOTES.md)"
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()  # ours, but not answering: replace it
            (WEATHER_DIR / "logs").mkdir(exist_ok=True)
            self._log = open(WEATHER_DIR / "logs" / "service.log", "a", encoding="utf-8")  # noqa: SIM115
            self._log.write(f"\n--- started by the planner server {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            self._log.flush()
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            # cwd is the weather folder so it finds its own .env and sample data.
            self.proc = subprocess.Popen(
                [str(py), "web_app.py", "--no-browser", "--port", str(self.port)],
                cwd=str(WEATHER_DIR), stdout=self._log, stderr=subprocess.STDOUT, creationflags=flags)
            t0 = time.monotonic()
            while time.monotonic() - t0 < START_TIMEOUT_S:
                if self.proc.poll() is not None:
                    return f"failed to start (exit {self.proc.returncode}); see agents/weather/logs/service.log"
                if self.alive(timeout=1.0):
                    return f"started (pid {self.proc.pid}) in {time.monotonic() - t0:.1f} s"
                time.sleep(0.4)
            return f"started (pid {self.proc.pid}) but not answering after {START_TIMEOUT_S:.0f} s"

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self._log is not None:
            self._log.close()
            self._log = None
