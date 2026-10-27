"""JDBC client for Zetaris Lightning. One statement per call, rows as dicts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import JDBC_DRIVER_CLASS, Settings


class ZetarisError(RuntimeError):
    pass


def _short(text: Any, n: int = 400) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "..."


class JdbcClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._conn = None
        self._cur = None

    def connect(self) -> None:
        if self._conn is not None:
            return
        s = self._s
        if not s.zetaris_username or not s.zetaris_password:
            raise ZetarisError("ZETARIS_USERNAME / ZETARIS_PASSWORD not set (check ZETARIS_ENV_FILE)")
        if not Path(s.zetaris_jdbc_jar).is_file():
            raise ZetarisError(f"JDBC driver jar not found: {s.zetaris_jdbc_jar}")
        if not (Path(s.java_home) / "bin").is_dir():
            raise ZetarisError(f"JAVA_HOME is not a JDK: {s.java_home}")
        os.environ["JAVA_HOME"] = s.java_home
        try:
            import jaydebeapi
        except ImportError as e:  # pragma: no cover
            raise ZetarisError("jaydebeapi is not installed (pip install -r requirements.txt)") from e
        try:
            self._conn = jaydebeapi.connect(
                JDBC_DRIVER_CLASS,
                s.zetaris_jdbc_url,
                [s.zetaris_username, s.zetaris_password],
                s.zetaris_jdbc_jar,
            )
        except Exception as e:
            raise ZetarisError(f"cannot connect to {s.zetaris_jdbc_url}: {_short(e)}") from e
        self._cur = self._conn.cursor()

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Run exactly one statement and return its rows as dicts."""
        stmt = sql.strip().rstrip(";").strip()
        if ";" in stmt:
            raise ZetarisError("one statement per call")
        self.connect()
        assert self._cur is not None
        try:
            self._cur.execute(stmt)
        except Exception as e:
            raise ZetarisError(f"{_short(e)}\n  statement: {stmt}") from e
        try:
            rows = self._cur.fetchall()
        except Exception:
            return []
        cols = [d[0] for d in (self._cur.description or [])]
        return [dict(zip(cols, (_py(v) for v in row))) for row in rows]

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._cur = None


def _py(value: Any) -> Any:
    """Coerce JPype boxed values to plain Python."""
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    text = str(value)
    try:
        return float(text) if "." in text else int(text)
    except (TypeError, ValueError):
        return text
