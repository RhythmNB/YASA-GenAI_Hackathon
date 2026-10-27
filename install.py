"""Set up Insightor on this machine, from a fresh clone to a ready planner.

    python install.py            # everything; safe to run again
    python install.py --check    # only report what is in place

Needs first (see README.md, "Before you start"): Python 3.11+, a JDK, Docker
with the Zetaris Lightning platform running, the Zetaris JDBC driver jar, and
the Meterless Nightshift app (optional: without it the prose comes from
templates). Everything after that is done here:

  1. finds the JDK, the JDBC jar, the Zetaris container and the Nightshift token
  2. clones zetaris/getting-started next to this repository (the pertussis and
     guidance agents use its Zetaris client) and links it in
  3. writes the settings: getting-started/.env.local, agents/wastewater/.env,
     agents/weather/.env (existing values are kept; secrets are never printed)
  4. installs the Python packages, and the weather service's own .venv
  5. loads the data into Zetaris: the two CDC wastewater exports, the pertussis
     REST table and views with the census and guidance tables, and the weather
     Postgres (NWS forecasts and alerts) as the datasource weather_pg
  6. checks every table answers through Zetaris

Each step skips what is already done, so a second run only checks."""

from __future__ import annotations

import argparse
import getpass
import glob
import importlib
import importlib.util
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent
AGENTS = REPO / "agents"
WASTEWATER = AGENTS / "wastewater"
PERTUSSIS = AGENTS / "pertussis_guidance"
WEATHER = AGENTS / "weather"
WINDOWS = sys.platform == "win32"

GETTING_STARTED_GIT = "https://github.com/zetaris/getting-started.git"
JDBC_URL = "jdbc:zetaris:lightning@localhost:10000"
NIGHTSHIFT_URL = "http://127.0.0.1:8088/v1"
SHARED = "/home/zetaris/customer-data/shared"  # where Zetaris filestore tables read files, inside the driver container

# The two CDC NWSS exports behind wastewater.sars_cov_2 and wastewater.influenza_a.
WASTEWATER_TABLES = [
    ("sars_cov_2", "SARS-CoV-2", "g653-rqe2", "01_wastewater_create.sql"),
    ("influenza_a", "Influenza_A", "ymmh-divb", "02_influenza_a_create.sql"),
]
PLACEHOLDERS = {"", "change-me", "your-zetaris-password"}


# ------------------------------------------------------------------ output

def step(title: str) -> None:
    print(f"\n== {title}")


def ok(msg: str) -> None:
    print(f"   ok    {msg}")


def info(msg: str) -> None:
    print(f"   ..    {msg}")


def warn(msg: str) -> None:
    print(f"   WARN  {msg}")


class SetupError(RuntimeError):
    pass


def run(cmd: list[str], check: bool = True, quiet: bool = False, **kw) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if check and res.returncode != 0:
        raise SetupError(f"{' '.join(cmd[:4])} failed:\n{(res.stderr or res.stdout).strip()[-800:]}")
    if not quiet and res.stdout.strip():
        for line in res.stdout.strip().splitlines()[-3:]:
            info(line)
    return res


# ------------------------------------------------------------------ .env files

def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def merge_env(path: Path, values: dict[str, str], force: frozenset[str] = frozenset()) -> list[str]:
    """Set keys that are missing, empty or still a placeholder (and the `force`
    keys always). Comments and other keys are left as they are. Returns the
    names it changed."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    have = read_env(path)
    changed = []
    for key, value in values.items():
        if value is None or (key not in force and have.get(key, "") not in PLACEHOLDERS):
            continue
        if have.get(key) == value:
            continue
        line = f"{key}={value}"
        if re.search(rf"^{re.escape(key)}=", text, re.M):
            text = re.sub(rf"^{re.escape(key)}=.*$", lambda _m: line, text, count=1, flags=re.M)
        else:
            text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
        changed.append(key)
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


# ------------------------------------------------------------------ 1. what is on this machine

def find_java_home(given: str | None, env_local: dict[str, str]) -> str | None:
    exe = "java.exe" if WINDOWS else "java"
    candidates = [given, os.environ.get("JAVA_HOME"), env_local.get("JAVA_HOME")]
    try:
        res = subprocess.run(["java", "-XshowSettings:properties", "-version"], capture_output=True, text=True)
        m = re.search(r"java\.home = (.+)", res.stderr)
        if m:
            candidates.append(m.group(1).strip())
    except OSError:
        pass
    if sys.platform == "darwin":
        res = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True)
        candidates.append(res.stdout.strip() if res.returncode == 0 else None)
    for home in candidates:
        if home and (Path(home) / "bin" / exe).is_file():
            return str(Path(home))
    return None


def find_jdbc_jar(given: str | None, env_local: dict[str, str]) -> str | None:
    for jar in (given, os.environ.get("ZETARIS_JDBC_JAR"), env_local.get("ZETARIS_JDBC_JAR")):
        if jar and Path(jar).is_file():
            return str(Path(jar).resolve())
    # The platform bundle ships it in zetaris-platform/jdbc/; look beside this repo and in the home folder.
    roots = [REPO.parent, REPO.parent.parent, Path.home(), Path.home() / "Downloads"]
    if WINDOWS:
        roots += [Path(f"{d}:/") for d in "CDEF" if Path(f"{d}:/").exists()]
    for root in roots:
        for pattern in ("*/jdbc/ndp-jdbc-driver-*.jar", "*/*/jdbc/ndp-jdbc-driver-*.jar"):
            hits = sorted(glob.glob(str(root / pattern)))
            if hits:
                return str(Path(hits[-1]).resolve())
    return None


def find_driver_container() -> str | None:
    res = run(["docker", "ps", "--format", "{{.Names}}"], check=False, quiet=True)
    names = res.stdout.split()
    return next((n for n in names if "zetaris" in n and "driver" in n), None) or \
        next((n for n in names if n.endswith("driver-1")), None)


def find_nightshift_token() -> Path | None:
    bases = [os.environ.get("LOCALAPPDATA"), Path.home() / "AppData" / "Local",
             Path.home() / "Library" / "Application Support", Path.home() / ".local" / "share"]
    for base in bases:
        if base and (Path(base) / "ai.meterless.runtime" / "proxy-token").is_file():
            return Path(base) / "ai.meterless.runtime" / "proxy-token"
    return None


def nightshift_answers(token: str | None) -> bool:
    req = urllib.request.Request(f"{NIGHTSHIFT_URL}/models", headers={"Authorization": f"Bearer {token or ''}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def check_machine(a) -> dict:
    step("1. What is on this machine")
    if sys.version_info < (3, 11):
        raise SetupError(f"Python 3.11 or newer is needed (this is {sys.version.split()[0]}).")
    ok(f"Python {sys.version.split()[0]} ({sys.executable})")

    gs = Path(a.getting_started).resolve() if a.getting_started else REPO.parent / "getting-started"
    env_local = read_env(gs / ".env.local")

    java = find_java_home(a.java_home, env_local)
    if not java:
        raise SetupError("No JDK found. Install one (JDK 17 or newer), then pass --java-home or set JAVA_HOME.")
    ok(f"JDK {java}")

    jar = find_jdbc_jar(a.jdbc_jar, env_local)
    if not jar:
        raise SetupError("The Zetaris JDBC driver jar (ndp-jdbc-driver-*.jar) was not found. It ships in the "
                         "platform bundle's jdbc/ folder; pass its path with --jdbc-jar.")
    ok(f"JDBC driver {jar}")

    if shutil.which("docker") is None or run(["docker", "info"], check=False, quiet=True).returncode != 0:
        raise SetupError("Docker is not running. Start Docker Desktop and the Zetaris platform (docker compose up -d).")
    driver = find_driver_container()
    if not driver:
        raise SetupError("No Zetaris driver container is running. Start the platform: in its folder, docker compose up -d.")
    nets = run(["docker", "inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", driver],
               quiet=True).stdout.split()
    ok(f"Zetaris container {driver} (network {nets[0] if nets else '?'})")

    token_file = find_nightshift_token()
    token = token_file.read_text(encoding="utf-8").strip() if token_file else env_local.get("METERLESS_API_KEY")
    if nightshift_answers(token):
        ok(f"Nightshift answers at {NIGHTSHIFT_URL}")
    else:
        warn("Nightshift is not answering at 127.0.0.1:8088. Plans still work; the prose comes from templates. "
             "Open the Nightshift app and add an NVIDIA key under Setup > Providers to use the models.")

    user = a.zetaris_user or os.environ.get("ZETARIS_USERNAME") or env_local.get("ZETARIS_USERNAME") or ""
    password = os.environ.get("ZETARIS_PASSWORD") or env_local.get("ZETARIS_PASSWORD") or ""
    if not user and not a.check:
        default = "admin@zetaris.com"
        user = input(f"   Zetaris username, the one you sign in to localhost:3000 with [{default}]: ").strip() or default
    user = user or "admin@zetaris.com"
    if not password and not a.check:
        password = getpass.getpass(f"   Zetaris password for {user}: ")
    return {"gs": gs, "java": java, "jar": jar, "driver": driver, "network": nets[0] if nets else "zetaris_default",
            "token_file": token_file, "token": token, "user": user, "password": password}


# ------------------------------------------------------------------ 2. getting-started

def link_dir(link: Path, target: Path) -> None:
    if link.exists():
        return
    if WINDOWS:  # a junction needs no admin rights, unlike a symlink
        run(["cmd", "/c", "mklink", "/J", str(link), str(target)], quiet=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def getting_started(m: dict, check: bool) -> None:
    step("2. The getting-started checkout")
    gs: Path = m["gs"]
    if not (gs / "scripts" / "zetaris_sql.py").is_file():
        if check:
            warn(f"missing: {gs}")
            return
        if shutil.which("git") is None:
            raise SetupError(f"git is needed to clone {GETTING_STARTED_GIT} into {gs}.")
        info(f"cloning {GETTING_STARTED_GIT} into {gs}")
        run(["git", "clone", "--depth", "1", GETTING_STARTED_GIT, str(gs)], quiet=True)
    ok(f"{gs}")
    # Its find_java_home() only looks for bin/java, which does not exist on Windows (bin/java.exe).
    script = gs / "scripts" / "zetaris_sql.py"
    old = 'if home and (Path(home) / "bin" / "java").is_file():'
    new = 'if home and ((Path(home) / "bin" / "java").is_file() or (Path(home) / "bin" / "java.exe").is_file()):'
    text = script.read_text(encoding="utf-8")
    if old in text and not check:
        script.write_text(text.replace(old, new), encoding="utf-8")
        ok("patched zetaris_sql.py to find java.exe")
    link = PERTUSSIS / "getting-started"
    if not check:
        link_dir(link, gs)
    (ok if link.exists() else warn)(f"{link.relative_to(REPO)} -> {gs}")


# ------------------------------------------------------------------ 3. settings

def settings(m: dict, a) -> None:
    step("3. Settings (.env files, git-ignored)")
    if a.check:
        for p in (m["gs"] / ".env.local", WASTEWATER / ".env", WEATHER / ".env"):
            (ok if p.is_file() else warn)(f"{p}{'' if p.is_file() else ' missing'}")
        return
    java, jar = m["java"].replace("\\", "/"), m["jar"].replace("\\", "/")

    env_local = m["gs"] / ".env.local"
    if not env_local.is_file() and (m["gs"] / ".env.example").is_file():
        shutil.copy(m["gs"] / ".env.example", env_local)
    changed = merge_env(env_local, {
        "ZETARIS_BASE_URL": "http://localhost:3000", "ZETARIS_REST_URL": "http://localhost:8888/api/v1.0",
        "ZETARIS_ORG_ID": "1", "ZETARIS_JDBC_URL": JDBC_URL, "ZETARIS_JDBC_JAR": jar,
        "ZETARIS_USERNAME": m["user"], "ZETARIS_PASSWORD": m["password"], "JAVA_HOME": java,
        "METERLESS_BASE_URL": NIGHTSHIFT_URL, "METERLESS_API_KEY": m["token"],
        "METERLESS_MODEL": "nvidia/nemotron-3.5-lightning-30b-a3b", "METERLESS_APP": "visit-planner-cloud",
    })
    ok(f"{env_local}  {'set ' + ', '.join(changed) if changed else 'unchanged'}")

    ww = WASTEWATER / ".env"
    if not ww.is_file():
        shutil.copy(WASTEWATER / ".env.example", ww)
    changed = merge_env(ww, {
        "ZETARIS_ENV_FILE": str(env_local).replace("\\", "/"), "JAVA_HOME_DEFAULT": java, "ZETARIS_JDBC_JAR": jar,
        "NIGHTSHIFT_TOKEN_FILE": str(m["token_file"]).replace("\\", "/") if m["token_file"] else None,
    }, force=frozenset({"ZETARIS_ENV_FILE"}))
    ok(f"{ww.relative_to(REPO)}  {'set ' + ', '.join(changed) if changed else 'unchanged'}")

    wx = WEATHER / ".env"
    if not wx.is_file():
        shutil.copy(WEATHER / ".env.example", wx)
    zetaris_mode = not a.no_weather_db
    changed = merge_env(wx, {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(18),
        "ZETARIS_JDBC_URL": JDBC_URL, "ZETARIS_USER": m["user"], "ZETARIS_PASSWORD": m["password"],
        "ZETARIS_JDBC_JAR": jar, "JAVA_HOME": java,
        "WEATHER_MODE": "zetaris" if zetaris_mode else "sample",
        "WEATHER_REFRESH_POSTGRES": "1" if zetaris_mode else "0",
        "SAMPLE_DB": str(WEATHER / "sample_data" / "weather_sample.db").replace("\\", "/"),
        "LLM_MODE": "nightshift", "WEATHER_PORT": "8770", "ZETARIS_NETWORK": m["network"],
        # The weather service finds the Windows token file itself; elsewhere it needs the key.
        "NIGHTSHIFT_API_KEY": None if WINDOWS or not m["token"] else m["token"],
    }, force=frozenset({"WEATHER_MODE", "WEATHER_REFRESH_POSTGRES", "SAMPLE_DB", "ZETARIS_NETWORK"}))
    ok(f"{wx.relative_to(REPO)}  {'set ' + ', '.join(changed) if changed else 'unchanged'}")


# ------------------------------------------------------------------ 4. Python packages

def packages(a) -> None:
    step("4. Python packages")
    venv_py = WEATHER / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    if a.check:
        missing = [p for p in ("jaydebeapi", "jpype", "httpx") if importlib.util.find_spec(p) is None]
        (warn if missing else ok)(f"planner packages {'missing: ' + ', '.join(missing) if missing else 'installed'}")
        (ok if venv_py.is_file() else warn)(f"weather .venv {'present' if venv_py.is_file() else 'missing'}")
        return
    run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
         "-r", str(WASTEWATER / "requirements.txt")], quiet=True)
    importlib.invalidate_caches()
    ok("planner and wastewater agent: jaydebeapi, JPype1, httpx")
    if not venv_py.is_file():
        run([sys.executable, "-m", "venv", str(WEATHER / ".venv")], quiet=True)
    run([str(venv_py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
         "-r", str(WEATHER / "requirements.txt")], quiet=True)
    ok(f"weather service: {venv_py.relative_to(REPO)}")


# ------------------------------------------------------------------ 5. data in Zetaris

class Zetaris:
    """A JDBC session that runs each statement as a plain Statement: the CDC
    REST URL contains `?`, which a PreparedStatement would read as a bind
    parameter ("Parameter #1 is unset")."""

    def __init__(self, m: dict) -> None:
        os.environ["JAVA_HOME"] = m["java"]
        import jaydebeapi
        self.conn = jaydebeapi.connect("com.zetaris.lightning.jdbc.LightningDriver", JDBC_URL,
                                       [m["user"], m["password"]], m["jar"])

    def execute(self, sql: str) -> list[list]:
        st = self.conn.jconn.createStatement()
        try:
            rows = []
            if st.execute(sql):
                rs = st.getResultSet()
                n = rs.getMetaData().getColumnCount()
                while rs.next() and len(rows) < 100:
                    rows.append([None if rs.getObject(c) is None else str(rs.getObject(c)) for c in range(1, n + 1)])
            return rows
        finally:
            st.close()

    def try_execute(self, sql: str) -> str:
        """'ok', 'exists' when the object is already there, or raises."""
        try:
            self.execute(sql)
            return "ok"
        except Exception as e:  # noqa: BLE001 - the driver raises java exceptions
            msg = str(e).lower()
            if "already exist" in msg or ("exists" in msg and "not exist" not in msg and "n't exist" not in msg):
                return "exists"
            raise SetupError(f"{' '.join(sql.split())[:120]}\n      {short_error(e)}") from None

    def drop_table(self, table: str) -> None:
        """Drop a Lightning table that exists but does not answer, so it can be created again:
        Zetaris accepts a filestore table whose file is missing and only fails when it is queried."""
        try:
            self.execute(f"DROP LIGHTNING DATABASE TABLE {table}")
            info(f"dropped {table}, which existed but did not answer")
        except Exception:  # noqa: BLE001 - it was not there
            pass

    def problem(self, table: str) -> str | None:
        """None when the table answers a query, else Zetaris's reason in one line."""
        try:
            self.execute(f"SELECT 1 FROM {table} LIMIT 1")
            return None
        except Exception as e:  # noqa: BLE001
            return short_error(e)

    def answers(self, table: str) -> bool:
        return self.problem(table) is None

    def close(self) -> None:
        self.conn.close()


def short_error(e: Exception) -> str:
    """The Lightning message between <<< >>>, without the Java exception chain."""
    text = str(e)
    m = re.search(r"<<<(.+?)>>>", text, re.S)
    return " ".join((m.group(1) if m else text.splitlines()[0]).split())[:300]


def hint(error: str) -> str:
    if "PATH_NOT_FOUND" in error or "Path does not exist" in error:
        return (f"the Zetaris container cannot read the file. install.py copies it into {SHARED} in the "
                "container whose name contains 'driver'; if your Zetaris bundle reads customer files from another "
                "container or folder, copy it there (docker cp) and run install.py again")
    if "Permission denied" in error:
        return f"the file is not readable by Zetaris; run: docker exec -u 0 <driver> chown -R zetaris:zetaris {SHARED}"
    if "TABLE_OR_VIEW_NOT_FOUND" in error:
        return "it was not created; run install.py again and look for the first error above"
    if "onnect" in error:
        return "Zetaris could not reach the source; check the container or the internet connection and run again"
    return "run install.py again; if it repeats, send the team this output"


def statements(sql_file: Path) -> list[str]:
    text = "\n".join(l for l in sql_file.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", text) if s.strip()]


def into_container(m: dict, files: list[Path], folder: str) -> None:
    run(["docker", "exec", "-u", "0", m["driver"], "mkdir", "-p", f"{SHARED}/{folder}"], quiet=True)
    for f in files:
        run(["docker", "cp", str(f), f"{m['driver']}:{SHARED}/{folder}/"], quiet=True)
    # Without this Zetaris reads the copied files as root's and reports "Permission denied".
    run(["docker", "exec", "-u", "0", m["driver"], "chown", "-R", "zetaris:zetaris", SHARED], quiet=True)


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "insightor-setup"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        done, mark = 0, 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if done - mark >= 50 << 20:
                info(f"{dest.name}: {done >> 20} MB")
                mark = done
    tmp.replace(dest)


def wastewater_data(m: dict, z: Zetaris, check: bool) -> None:
    for table, label, dataset, sql_name in WASTEWATER_TABLES:
        name = f"wastewater.{table}"
        problem = z.problem(name)
        if problem is None:
            ok(f"{name} answers")
            continue
        if check:
            warn(f"{name}: {problem}")
            continue
        if "TABLE_OR_VIEW_NOT_FOUND" not in problem:
            z.drop_table(name)
        data = WASTEWATER / "data"
        data.mkdir(exist_ok=True)
        have = sorted(data.glob(f"CDC_Wastewater_Data_for_{label}_*.csv"))
        if have:
            csv = have[-1]
        else:
            csv = data / f"CDC_Wastewater_Data_for_{label}_{date.today():%Y%m%d}.csv"
            info(f"downloading CDC NWSS {label} ({dataset}), a few hundred MB")
            download(f"https://data.cdc.gov/api/views/{dataset}/rows.csv?accessType=DOWNLOAD", csv)
        into_container(m, [csv], "wastewater")
        for sql in statements(WASTEWATER / "sql" / sql_name):
            # The create scripts name the export they were written against; point them at this one.
            z.try_execute(re.sub(r"CDC_Wastewater_Data_for_\S+?_\d{8}\.csv", csv.name, sql))
        problem = z.problem(name)
        if problem:
            raise SetupError(f"{name} was created from {csv.name} but does not answer:\n      {problem}\n"
                             f"      Likely cause: {hint(problem)}")
        ok(f"{name} created from {csv.name}")


def pertussis_data(m: dict, z: Zetaris, check: bool) -> None:
    targets = ("visitplanner.pertussis_state_rates", "refdata.cdc_guidance")
    problems = {t: z.problem(t) for t in targets}
    if not any(problems.values()):
        ok("visitplanner.pertussis_state_rates and refdata.cdc_guidance answer")
        return
    if check:
        for t, problem in problems.items():
            if problem:
                warn(f"{t}: {problem}")
        return
    # The views are rebuilt by name, so only the tables under them need dropping when they are broken.
    for table in ("refdata.census_state_pop_2025", "refdata.cdc_guidance", "cdc_rest.nndss_pertussis_2026"):
        problem = z.problem(table)
        if problem and "TABLE_OR_VIEW_NOT_FOUND" not in problem:
            z.drop_table(table)
    into_container(m, [PERTUSSIS / "data" / "census_state_pop_2025.csv"], "census")
    into_container(m, [PERTUSSIS / "data" / "cdc_guidance_2026-10-26.csv"], "guidance")
    for sql in statements(PERTUSSIS / "sql" / "setup.sql"):
        if not sql.upper().startswith("SELECT"):
            z.try_execute(sql)
    for t in ("cdc_rest.nndss_pertussis_2026", "refdata.census_state_pop_2025", *targets):
        problem = z.problem(t)
        if problem:
            raise SetupError(f"{t} does not answer:\n      {problem}\n      Likely cause: {hint(problem)}")
    ok("cdc_rest.nndss_pertussis_2026, refdata.census_state_pop_2025, refdata.cdc_guidance, visitplanner views")


def weather_data(m: dict, z: Zetaris, a) -> None:
    if a.no_weather_db:
        info("--no-weather-db: the weather service reads its offline SQLite copy")
        return
    problem = z.problem("weather_pg.cities")
    if problem is None:
        ok("weather_pg answers")
        return
    if a.check:
        warn(f"weather_pg: {problem}")
        return
    env = {**os.environ, "ZETARIS_NETWORK": m["network"]}
    run(["docker", "compose", "up", "-d"], cwd=WEATHER, env=env, quiet=True)
    wenv = read_env(WEATHER / ".env")
    for _ in range(60):
        if run(["docker", "exec", "weather-db", "pg_isready", "-U", wenv.get("POSTGRES_USER", "weather")],
               check=False, quiet=True).returncode == 0:
            break
        time.sleep(1)
    ok("weather-db (Postgres) running")
    venv_py = WEATHER / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    info("downloading NWS forecasts and alerts for 217 cities")
    run([str(venv_py), "ingest_weather.py"], cwd=WEATHER)
    have = {r[0].lower() for r in z.execute("SHOW DATASOURCES")}
    if "weather_pg" in have and z.problem("weather_pg.cities"):
        z.execute("DROP DATASOURCE weather_pg")  # registered earlier but broken (old password, tables missing)
        have.discard("weather_pg")
        info("dropped weather_pg, which existed but did not answer")
    if "weather_pg" not in have:
        # Zetaris allows only letters, digits, _ . - and , in a description.
        z.try_execute(
            'CREATE DATASOURCE weather_pg DESCRIBE BY "Weather Postgres, NWS forecasts and alerts" OPTIONS ('
            'jdbcdriver "org.postgresql.Driver", '
            f'jdbcurl "jdbc:postgresql://weather-db:5432/{wenv.get("POSTGRES_DB", "weather")}", '
            f'username "{wenv.get("POSTGRES_USER", "weather")}", password "{wenv["POSTGRES_PASSWORD"]}", '
            'fetchsize "1000")')
        z.try_execute('REGISTER DATASOURCE TABLES ("forecast_periods", "weather_alerts", "cities") FROM weather_pg')
    problem = z.problem("weather_pg.cities")
    if problem:
        raise SetupError(f"weather_pg was registered but does not answer:\n      {problem}\n"
                         f"      Likely cause: Zetaris reaches the database as weather-db:5432 on the Docker network "
                         f"{m['network']}; check that `docker ps` shows weather-db, then run install.py again")
    ok("weather_pg registered: forecast_periods, weather_alerts, cities")


def zetaris_data(m: dict, a) -> Zetaris:
    step("5. Data in Zetaris")
    if not m["password"]:
        raise SetupError("No Zetaris password: set ZETARIS_PASSWORD in getting-started/.env.local, or run without --check.")
    try:
        z = Zetaris(m)
    except Exception as e:  # noqa: BLE001
        raise SetupError(f"Could not sign in to Zetaris over JDBC ({JDBC_URL}): {str(e).splitlines()[0][:300]}") from None
    wastewater_data(m, z, a.check)
    pertussis_data(m, z, a.check)
    weather_data(m, z, a)
    return z


# ------------------------------------------------------------------ 6. check

def verify(z: Zetaris, a) -> bool:
    step("6. Check")
    checks = [("wastewater.sars_cov_2", "COVID-19 wastewater"), ("wastewater.influenza_a", "flu A wastewater"),
              ("visitplanner.pertussis_state_rates", "whooping cough by state"),
              ("refdata.cdc_guidance", "CDC guidance")]
    if not a.no_weather_db:
        checks.append(("weather_pg.forecast_periods", "NWS forecasts"))
    good = True
    for table, what in checks:
        problem = z.problem(table)
        if problem is None:
            ok(f"{what}: {table}")
        else:
            warn(f"{what}: {table} does not answer: {problem}")
            info(f"likely cause: {hint(problem)}")
            good = False
    return good


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="only report what is in place; change nothing")
    p.add_argument("--getting-started", help="where the getting-started checkout is or goes (default: next to this repo)")
    p.add_argument("--java-home", help="JDK folder, if it is not found")
    p.add_argument("--jdbc-jar", help="path to ndp-jdbc-driver-*.jar, if it is not found")
    p.add_argument("--zetaris-user", help="Zetaris username; asked for when it is not saved yet (default admin@zetaris.com)")
    p.add_argument("--no-weather-db", action="store_true",
                   help="skip the weather Postgres; the weather service reads its offline copy instead of Zetaris")
    a = p.parse_args()
    try:
        m = check_machine(a)
        getting_started(m, a.check)
        settings(m, a)
        packages(a)
        z = zetaris_data(m, a)
        good = verify(z, a)
        z.close()
    except SetupError as e:
        print(f"\n   FAILED  {e}\n")
        return 1
    if good:
        print("\nReady. Start the planner with\n\n    python planner/frontend/server.py --port 8765\n\n"
              "and open http://127.0.0.1:8765/  (http://127.0.0.1:8765/?demo=1 needs no services at all).\n")
        return 0
    print("\nSome tables do not answer; the reason is printed next to each. Fix that and run "
          "`python install.py` again: it rebuilds any table that exists but does not answer.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
