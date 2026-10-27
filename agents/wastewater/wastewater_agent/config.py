"""Configuration: environment files, Zetaris, Nightshift and memory paths.

Precedence: process environment, then `<agent root>/.env`, then the Zetaris
`.env.local` from the getting-started checkout. Secrets are never printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE_DIR.parent

# install.py clones getting-started next to this repository and writes ZETARIS_ENV_FILE.
DEFAULT_ZETARIS_ENV_FILE = AGENT_ROOT.parents[2] / "getting-started" / ".env.local"
DEFAULT_JAVA_HOME = r"F:\jdk-23.0.2"
DEFAULT_JDBC_URL = "jdbc:zetaris:lightning@localhost:10000"
DEFAULT_JDBC_JAR = r"F:\zetaris-platform\jdbc\ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar"
JDBC_DRIVER_CLASS = "com.zetaris.lightning.jdbc.LightningDriver"

DEFAULT_NIGHTSHIFT_BASE_URL = "http://127.0.0.1:8088/v1"
# Models are named directly; the meterless/auto and meterless/fast aliases are not used.
# Every completion tries these in order, and a model that fails is skipped for a while
# before anything falls back to the offline templates. Override with NIGHTSHIFT_MODELS=a,b.
NIGHTSHIFT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NIGHTSHIFT_MODELS = (
    NIGHTSHIFT_MODEL,
    "nvidia/nemotron-3.5-lightning-30b-a3b",
)
NIGHTSHIFT_APP = "wastewater-agent"


class ConfigError(RuntimeError):
    pass


def _load_env_file(path: Path) -> bool:
    """Load KEY=VALUE lines into os.environ without overriding set values."""
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)
    return True


@dataclass
class Settings:
    zetaris_jdbc_url: str
    zetaris_jdbc_jar: str
    zetaris_username: str
    zetaris_password: str
    java_home: str
    nightshift_base_url: str
    nightshift_token: str | None
    nightshift_token_source: str
    nightshift_models: tuple[str, ...]
    hmem_dir: Path
    zetaris_env_file: Path | None


def _default_token_file() -> Path:
    """The Windows app's proxy-token, else the macOS app's runtime-token."""
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    windows = Path(local) / "ai.meterless.runtime" / "proxy-token"
    if windows.is_file():
        return windows
    # The macOS app folder carries the build in its name (ai.meterless.nightshift.m1m4).
    mac = sorted((Path.home() / "Library" / "Application Support").glob("ai.meterless.nightshift*/runtime-token"))
    return mac[0] if mac else windows


def load_settings() -> Settings:
    _load_env_file(AGENT_ROOT / ".env")
    zetaris_env = Path(os.environ.get("ZETARIS_ENV_FILE", str(DEFAULT_ZETARIS_ENV_FILE)))
    zetaris_env_used = zetaris_env if _load_env_file(zetaris_env) else None

    java_home = os.environ.get("JAVA_HOME") or os.environ.get("JAVA_HOME_DEFAULT", DEFAULT_JAVA_HOME)
    os.environ["JAVA_HOME"] = java_home

    token = os.environ.get("NIGHTSHIFT_TOKEN")
    token_source = "env NIGHTSHIFT_TOKEN"
    if not token:
        token_file = Path(os.environ.get("NIGHTSHIFT_TOKEN_FILE", str(_default_token_file())))
        token_source = f"file {token_file}"
        token = token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else None

    return Settings(
        zetaris_jdbc_url=os.environ.get("ZETARIS_JDBC_URL", DEFAULT_JDBC_URL),
        zetaris_jdbc_jar=os.environ.get("ZETARIS_JDBC_JAR", DEFAULT_JDBC_JAR),
        zetaris_username=os.environ.get("ZETARIS_USERNAME", ""),
        zetaris_password=os.environ.get("ZETARIS_PASSWORD", ""),
        java_home=java_home,
        nightshift_base_url=os.environ.get("NIGHTSHIFT_BASE_URL", DEFAULT_NIGHTSHIFT_BASE_URL).rstrip("/"),
        nightshift_token=token,
        nightshift_token_source=token_source,
        nightshift_models=tuple(
            m.strip() for m in os.environ.get("NIGHTSHIFT_MODELS", ",".join(NIGHTSHIFT_MODELS)).split(",") if m.strip()
        ) or NIGHTSHIFT_MODELS,
        hmem_dir=Path(os.environ.get("HMEM_DIR", str(AGENT_ROOT / ".hmem"))),
        zetaris_env_file=zetaris_env_used,
    )
