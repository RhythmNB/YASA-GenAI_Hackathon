"""Local web server for the wastewater visit planner.

Serves the static frontend and a small JSON API over the existing agent.
Standard library only. Run from the `wastewater/` folder:

    python frontend/server.py [--port 8765] [--host 127.0.0.1]

Endpoints
    GET  /api/geocode?q=<city>          typed city -> candidates with county, state and coordinates
    GET  /api/status                    Zetaris, Nightshift and memory counts
    POST /api/ask        {question, county?}  run the agent (county narrows to that county's sites)
    GET  /api/answers                   this process's answers, newest first
    GET  /api/answers/<id>              one answer record (JSON)
    GET  /api/answers/<id>/report.md    Markdown report (download)
    GET  /api/memory?layer=working      memory records
    POST /api/feedback   {id, kind}     helpful | not_helpful | wrong
    GET  /api/states                    state codes and names
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent  # planner/frontend -> repo root
sys.path.insert(0, str(REPO))                                 # the planner package
sys.path.insert(0, str(REPO / "agents" / "wastewater"))      # the wastewater_agent package

from wastewater_agent.agent import Agent  # noqa: E402
from wastewater_agent.agent.writer import render_facts  # noqa: E402
from wastewater_agent.config import load_settings  # noqa: E402
from wastewater_agent.hmem import HMem  # noqa: E402
from wastewater_agent.llm import NightshiftProvider, ProviderError, ProviderUnauthorized  # noqa: E402
from wastewater_agent.states import US_STATES, state_name  # noqa: E402
from wastewater_agent.zetaris import JdbcClient, ZetarisError, sql  # noqa: E402
from planner.planner_agent import PlannerAgent  # noqa: E402
from planner.trip import TripRequest  # noqa: E402
from weather_service import WeatherSupervisor  # noqa: E402  (next to this file)

STATIC_DIR = HERE / "static"
DISCLAIMER = (
    "Wastewater surveillance is a population-level signal from the CDC NWSS export loaded in Zetaris. "
    "It is not medical or travel advice and does not describe any individual's risk."
)


class AgentService:
    """One agent per process (the JVM can start only once); calls are serialised."""

    def __init__(self) -> None:
        self.settings = load_settings()
        self._agent: Agent | None = None
        self._lock = threading.Lock()
        self.answers: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.plans: dict[str, dict[str, Any]] = {}
        self.plan_order: list[str] = []
        self._planner: PlannerAgent | None = None

    @property
    def agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(self.settings)
        return self._agent

    @property
    def planner(self) -> PlannerAgent:
        if self._planner is None:
            self._planner = PlannerAgent(self.settings, agent=self.agent)
        return self._planner

    def plan(self, trip: dict[str, Any], progress: Any = None) -> dict[str, Any]:
        request = TripRequest.from_dict(trip)  # ValueError on bad input
        if WEATHER is not None:
            state = WEATHER.ensure()  # restarts the weather service if it has died since the last plan
            if not state.startswith("running"):
                print(f"weather service: {state}", flush=True)
        with self._lock:
            record = self.planner.run(request, progress=progress).to_dict()
        self.plans[record["id"]] = record
        self.plan_order.insert(0, record["id"])
        return record

    def ask(self, question: str, county: str | None = None, pathogen: str | None = None,
            progress: Any = None) -> dict[str, Any]:
        with self._lock:
            t0 = time.perf_counter()
            answer = self.agent.ask(question, county=county, pathogen=pathogen, progress=progress)
            record = serialise_answer(question, answer, time.perf_counter() - t0)
        self.answers[record["id"]] = record
        self.order.insert(0, record["id"])
        return record

    def status(self) -> dict[str, Any]:
        s = self.settings
        out: dict[str, Any] = {"zetaris": {}, "nightshift": {}, "memory": {}}
        from wastewater_agent import pathogens

        client = JdbcClient(s)
        try:
            rows = client.query(sql.latest_sample_date())
            out["zetaris"] = {"ok": True, "url": s.zetaris_jdbc_url, "latestSample": rows[0].get("latest_sample_date") if rows else None, "tables": {}}
            for p in pathogens.PATHOGENS.values():
                try:
                    r2 = client.query(sql.latest_sample_date(pathogen=p))
                    out["zetaris"]["tables"][p.key] = {"table": p.table, "ok": True, "latestSample": r2[0].get("latest_sample_date") if r2 else None}
                except ZetarisError as e2:
                    out["zetaris"]["tables"][p.key] = {"table": p.table, "ok": False, "error": str(e2)[:120]}
        except ZetarisError as e:
            out["zetaris"] = {"ok": False, "url": s.zetaris_jdbc_url, "error": str(e)[:200]}
        finally:
            client.close()
        ns = NightshiftProvider(s.nightshift_base_url, s.nightshift_token, models=s.nightshift_models)
        state, models = ns.readiness()
        out["nightshift"] = {"ok": state == "online", "state": state, "url": s.nightshift_base_url,
                             "routes": [m["id"] for m in models if str(m["id"]).startswith("meterless/") and m["availability"] in ("ready", "cloud")]}
        with self._lock:
            hmem = self.agent.hmem if self._agent else HMem(s.hmem_dir)
            out["memory"] = hmem.counts()
        weather_url = (os.environ.get("WEATHER_SERVICE_URL") or "http://127.0.0.1:8770").rstrip("/")
        try:
            r = httpx.get(f"{weather_url}/api/status", timeout=5.0)
            out["weather"] = {"ok": r.status_code == 200, "url": weather_url,
                              **(r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"})}
        except (httpx.HTTPError, ValueError) as e:
            out["weather"] = {"ok": False, "url": weather_url, "error": e.__class__.__name__}
        return out

    def memory(self, layer: str | None) -> list[dict[str, Any]]:
        with self._lock:
            hmem = self.agent.hmem if self._agent else HMem(self.settings.hmem_dir)
            recs = hmem.list(layer)
        return [
            {"id": r.id, "layer": r.layer, "content": r.content, "confidence": r.confidence,
             "accessCount": r.accessCount, "createdAt": r.createdAt, "tags": r.tags, "entities": r.entities,
             "supersededBy": r.supersededBy, "metadata": r.metadata}
            for r in recs
        ]

    def feedback(self, memory_id: str, kind: str) -> dict[str, Any]:
        with self._lock:
            hmem = self.agent.hmem if self._agent else HMem(self.settings.hmem_dir)
            rec = hmem.feedback(memory_id, kind)
        return {"id": rec.id, "confidence": rec.confidence, "accessCount": rec.accessCount, "tags": rec.tags}


# -- geocoding: typed city -> county -> state ---------------------------------
# Open-Meteo's geocoder (no key) returns admin1 (state) and admin2 (county) for
# US places. The agent works per state, so the state code is what the check
# uses; county and coordinates feed the page (weather, labels).

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_STATE_CODE_BY_NAME = {name: code for name, code in US_STATES.items()}
_GEOCODE_CACHE: dict[str, list[dict[str, Any]]] = {}
# One keep-alive client: a fresh TLS handshake per keystroke was most of the latency.
_HTTP = httpx.Client(timeout=8.0, headers={"Accept-Encoding": "gzip"})


def county_label(admin2: str | None) -> str | None:
    if not admin2:
        return None
    low = admin2.lower()
    if any(w in low for w in ("county", "parish", "borough", "city of", "municipio", "census area")):
        return admin2
    return f"{admin2} County"


def geocode(query: str, limit: int = 6) -> list[dict[str, Any]]:
    q = " ".join(query.split()).strip()
    if len(q) < 2:
        return []
    key = q.lower()
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    r = _HTTP.get(GEOCODE_URL, params={"name": q, "count": 10, "language": "en", "format": "json", "countryCode": "US"})
    r.raise_for_status()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in r.json().get("results", []) or []:
        if row.get("country_code") != "US":
            continue
        state_name = row.get("admin1") or ""
        code = _STATE_CODE_BY_NAME.get(state_name.lower())
        if not code:
            continue
        name = row.get("name") or q
        if (name, code) in seen:
            continue
        seen.add((name, code))
        county = county_label(row.get("admin2"))
        out.append({
            "name": name,
            "county": county,
            "state": state_name,
            "stateCode": code,
            "lat": row.get("latitude"),
            "lon": row.get("longitude"),
            "population": row.get("population"),
            "label": f"{name}, {code.upper()}",
            "detail": ", ".join(p for p in (county, state_name) if p),
        })
        if len(out) >= limit:
            break
    # Exact name first, then names starting with the query, then by population;
    # the geocoder's own order mixes in fuzzy matches such as "York" for "New York".
    def rank(p: dict[str, Any]) -> tuple[int, int, int]:
        n = str(p["name"]).lower()
        return (0 if n == key else 1 if n.startswith(key) else 2, 0 if key in n else 1, -(p.get("population") or 0))

    out.sort(key=rank)
    _GEOCODE_CACHE[key] = out
    return out


def serialise_answer(question: str, answer, elapsed: float) -> dict[str, Any]:
    facts = answer.facts
    return {
        "id": "ans_" + uuid.uuid4().hex[:10],
        "askedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "question": question,
        "text": answer.text,
        "provider": answer.provider,
        "elapsedSeconds": round(elapsed, 1),
        "plan": answer.plan.to_dict(),
        "region": facts.region or state_name(facts.state),
        "county": facts.county,
        "pathogen": facts.pathogen,
        "pathogenName": facts.pathogen_name,
        "facts": facts.to_dict(),
        "factSheet": render_facts(facts),
        "statements": list(answer.statements),
        "memoriesUsed": [{"id": m.id, "content": m.content, "confidence": m.confidence, "supersededBy": m.supersededBy}
                         for m in answer.memories_used],
        "memoryStored": answer.memory.id if answer.memory else None,
        "conflicts": answer.conflicts,
        "receipts": [
            {"receiptId": c.receipt_id, "routedModel": c.routed_model,
             "cache": ((c.raw.get("receipt") or {}).get("cache") or {}).get("status"),
             "reclaimed": ((c.raw.get("receipt") or {}).get("cache") or {}).get("losers_reclaimed")}
            for c in answer.completions
        ],
        "notes": list(answer.fallback_reasons),
        "retrieval": answer.retrieval_reason,
        "disclaimer": DISCLAIMER,
    }


def report_markdown(rec: dict[str, Any]) -> str:
    f = rec["facts"]
    w = f["window"]
    lines = [
        f"# Wastewater surveillance report: {rec['region']}",
        "",
        f"Generated {rec['askedAt']} by the wastewater agent (provider: {rec['provider']}).",
        "",
        "## Question",
        "",
        rec["question"],
        "",
        "## Answer",
        "",
        rec["text"],
        "",
        "## Key facts",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Region | {rec['region']} |",
        f"| Question type | {f['intent']} |",
        f"| Window | {w['start']} to {w['end']} ({w.get('label', '')}) |",
        f"| Coverage | {f['coverage']} (latest sample {f['latest_sample_date']}) |",
        f"| Samples | {f['samples']} |",
        f"| Positives | {f['positives']} |",
        f"| Positive share | {_pct(f['positive_share'])} |",
        f"| Sites | {f['sites']} |",
        f"| Mean concentration | {_num(f['mean_conc'])} {_units(f.get('units'))} |",
    ]
    if f.get("prior_window"):
        pw = f["prior_window"]
        lines += [
            f"| Preceding window | {pw['start']} to {pw['end']} |",
            f"| Preceding positive share | {_pct(f['prior_positive_share'])} ({f['prior_positives']} of {f['prior_samples']}) |",
            f"| Direction | {f['direction']} ({_signed(f['delta_share'])} percentage points) |",
        ]
    if f.get("fallback_window"):
        fw = f["fallback_window"]
        lines += [
            f"| Fallback window (most recent 7 days with data) | {fw['start']} to {fw['end']} |",
            f"| Fallback positive share | {_pct(f['fallback_positive_share'])} ({f['fallback_positives']} of {f['fallback_samples']}, {f['fallback_sites']} sites) |",
        ]
    lines += ["", "## Fact sheet given to the writer", "", "```", rec["factSheet"], "```", "", "## SQL executed", ""]
    lines += [f"{i}. `{s}`" for i, s in enumerate(rec["statements"], 1)]
    lines += ["", "## Memory", ""]
    lines += [f"- Used: {', '.join(m['id'] for m in rec['memoriesUsed']) or 'none'}", f"- Stored: {rec['memoryStored'] or 'none'}"]
    lines += ["", "## Compute receipts (Meterless Nightshift)", ""]
    lines += [f"- {r['receiptId'] or 'n/a'} via {r['routedModel'] or 'unknown'}" for r in rec["receipts"]] or ["- none (offline)"]
    if rec["notes"]:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in rec["notes"]]
    lines += ["", "---", "", rec["disclaimer"], ""]
    return "\n".join(lines)


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _num(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.1f}"


def _signed(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}"


def _units(units: Any) -> str:
    if not units:
        return ""
    first = units[0][0] if isinstance(units[0], (list, tuple)) else units[0]
    return str(first) + (" (mixed units)" if len(units) > 1 else "")


def plan_report_markdown(rec: dict[str, Any]) -> str:
    t, v = rec["trip"], rec["verdict"]
    lines = [f"# Travel plan: {t['toCity']}, {t['toState'].upper()}", "",
             f"{t['start']} to {t['end']}, from {t['fromCity']}, {t['fromState'].upper()}; "
             f"{t['adults']} adults, {t['children']} children; with: {', '.join(t['with']) or 'none stated'}.",
             "", f"## {v['label']}: {v.get('tagline', '')} ({v['level']})", "", v["reason"], "", rec["intro"], ""]
    for s in rec["sections"]:
        lines += [f"## {s['title']}  ({s['level']}{'' if s['status'] == 'ok' else ', ' + s['status']})", "", s["headline"], ""]
        if s["text"]:
            lines += [s["text"], ""]
        lines += [f"- {x}" for x in s["facts"]]
        lines += [f"- Caveat: {c}" for c in s["caveats"]]
        lines.append("")
    lines += ["## Before you go", ""] + [f"- [ ] {x}" for x in rec["precautions"]] + [""]
    if rec["bestDays"]:
        lines += ["## Best days outdoors", "", ", ".join(rec["bestDays"]), ""]
    lines += ["## Sources", ""] + [f"- [{s['title']}]({s['url']})" for s in rec["sources"]] + [""]
    ev = rec.get("evaluation") or {}
    if ev:
        lines += ["## Evaluation", "", f"{ev['final']} after {len(ev['rounds'])} review(s); kept draft {ev['chosenRound']}.", ""]
        for rp in ev.get("replans") or []:
            for r in rp["requests"]:
                lines.append(f"- Asked again: {r['source']} ({r['action']}): {r['reason']}; "
                             f"{r['before']['level']} -> {r['after']['level']}, kept the {r['kept']} answer")
        if ev.get("replans"):
            lines.append("")
        for r in ev["rounds"]:
            lines.append(f"- Round {r['round']}: {r['verdict']}" + (f" ({r['model']})" if r.get("model") else " (rules only)"))
            lines += [f"  - {i}" for i in r["issues"]]
        lines.append("")
    lines += ["## Models", ""] + [f"- {k}: {v or 'none'}" for k, v in rec["models"].items()] + [""]
    if rec["notes"]:
        lines += ["## Notes", ""] + [f"- {n}" for n in rec["notes"]] + [""]
    lines += [f"Generated {rec['createdAt']} in {rec['elapsedSeconds']} s" + (" (partial)" if rec["partial"] else ""), "", DISCLAIMER]
    return "\n".join(lines)


SERVICE = AgentService()
WEATHER: WeatherSupervisor | None = None  # set in main()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt, *args):  # quieter log
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self) -> None:
        # The page and script change often during development; never let the
        # browser pair a cached app.js with a newer index.html (or vice versa).
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    # -- helpers --

    def _ask_stream(self, question: str, county: str | None, pathogen: str | None) -> None:
        self._stream(lambda send: SERVICE.ask(question, county, pathogen, progress=send), "answer")

    def _plan_stream(self, trip: dict[str, Any]) -> None:
        self._stream(lambda send: SERVICE.plan(trip, progress=send), "plan")

    def _stream(self, run: Any, final_stage: str) -> None:
        """Newline-delimited JSON: one progress event per line while `run` works, then
        {"stage": final_stage, "record"/"plan": ...} or {"stage": "error", ...}. The
        connection closes when the body ends (no Content-Length), which fetch() handles."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        alive = True

        def send(event: dict[str, Any]) -> None:
            nonlocal alive
            if not alive:
                return
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                alive = False  # the page went away; let the run finish and be stored

        try:
            result = run(send)
            send({"stage": final_stage, ("record" if final_stage == "answer" else "plan"): result})
        except (KeyError, ValueError) as e:
            send({"stage": "error", "status": 400, "error": str(e)})
        except ProviderUnauthorized as e:
            send({"stage": "error", "status": 401, "error": str(e)})
        except ZetarisError as e:
            send({"stage": "error", "status": 502, "error": f"zetaris: {e}"})
        except ProviderError as e:
            send({"stage": "error", "status": 502, "error": f"nightshift: {e}"})

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, status: int, body: str, mime: str, filename: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    # -- routes --

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if not parts or parts[0] != "api":
            if url.path == "/":
                self.path = "/index.html"
            return super().do_GET()
        try:
            if parts[1:] == ["status"]:
                return self._json(200, SERVICE.status())
            if parts[1:] == ["geocode"]:
                q = (parse_qs(url.query).get("q") or [""])[0]
                try:
                    return self._json(200, {"query": q, "places": geocode(q)})
                except httpx.HTTPError as e:
                    return self._json(502, {"error": f"geocoding unavailable: {e.__class__.__name__}"})
            if parts[1:] == ["states"]:
                return self._json(200, {"states": sorted({c: n.title() for n, c in US_STATES.items()}.items(), key=lambda x: x[1])})
            if parts[1:] == ["answers"]:
                return self._json(200, {"answers": [_brief(SERVICE.answers[i]) for i in SERVICE.order]})
            if len(parts) >= 3 and parts[1] == "answers":
                rec = SERVICE.answers.get(parts[2])
                if rec is None:
                    return self._json(404, {"error": "no such answer"})
                if len(parts) == 3:
                    return self._json(200, rec)
                if parts[3] == "report.md":
                    return self._file(200, report_markdown(rec), "text/markdown", f"wastewater-report-{parts[2]}.md")
                if parts[3] == "answer.json":
                    return self._file(200, json.dumps(rec, indent=1, ensure_ascii=False), "application/json", f"wastewater-answer-{parts[2]}.json")
            if parts[1:] == ["plans"]:
                return self._json(200, {"plans": [{"id": p["id"], "createdAt": p["createdAt"], "trip": p["trip"], "verdict": p["verdict"],
                                                   "partial": p["partial"], "elapsedSeconds": p["elapsedSeconds"]}
                                                  for p in (SERVICE.plans[i] for i in SERVICE.plan_order)]})
            if len(parts) >= 3 and parts[1] == "plans":
                rec = SERVICE.plans.get(parts[2])
                if rec is None:
                    return self._json(404, {"error": "no such plan"})
                if parts[3:] == ["report.md"]:
                    return self._file(200, plan_report_markdown(rec), "text/markdown; charset=utf-8", f"{rec['id']}.md")
                return self._json(200, rec)
            if parts[1:] == ["memory"]:
                layer = (parse_qs(url.query).get("layer") or [None])[0]
                return self._json(200, {"memories": SERVICE.memory(layer)})
            return self._json(404, {"error": "not found"})
        except ZetarisError as e:
            return self._json(502, {"error": f"zetaris: {e}"})
        except ProviderError as e:
            return self._json(502, {"error": f"nightshift: {e}"})

    def do_POST(self) -> None:  # noqa: N802
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        data = self._body()
        try:
            if parts == ["api", "ask"]:
                question = str(data.get("question") or "").strip()
                if not question:
                    return self._json(400, {"error": "question is required"})
                county = str(data.get("county") or "").strip() or None
                pathogen = str(data.get("pathogen") or "").strip() or None
                if data.get("stream"):
                    return self._ask_stream(question, county, pathogen)
                try:
                    return self._json(200, SERVICE.ask(question, county, pathogen))
                except KeyError as e:
                    return self._json(400, {"error": str(e)})
            if parts == ["api", "plan"]:
                if data.get("stream"):
                    return self._plan_stream(data)
                try:
                    return self._json(200, SERVICE.plan(data))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if parts == ["api", "feedback"]:
                try:
                    return self._json(200, SERVICE.feedback(str(data.get("id")), str(data.get("kind"))))
                except KeyError:
                    return self._json(404, {"error": "no such memory"})
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            return self._json(404, {"error": "not found"})
        except ProviderUnauthorized as e:
            return self._json(401, {"error": str(e)})
        except ZetarisError as e:
            return self._json(502, {"error": f"zetaris: {e}"})
        except ProviderError as e:
            return self._json(502, {"error": f"nightshift: {e}"})


def _brief(rec: dict[str, Any]) -> dict[str, Any]:
    f = rec["facts"]
    return {"id": rec["id"], "askedAt": rec["askedAt"], "question": rec["question"], "region": rec["region"],
            "intent": f["intent"], "window": f["window"], "coverage": f["coverage"], "provider": rec["provider"],
            "positiveShare": f.get("positive_share"), "direction": f.get("direction")}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-weather", action="store_true", help="do not start the weather service on port 8770")
    args = p.parse_args()
    global WEATHER
    WEATHER = WeatherSupervisor(enabled=not args.no_weather)
    print(f"weather service ({WEATHER.url}): {WEATHER.ensure()}", flush=True)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"visit planner: http://{args.host}:{args.port}/  (static: {STATIC_DIR})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if SERVICE._agent is not None:
            SERVICE._agent.close()
        WEATHER.stop()  # only stops a weather service this server started
    return 0


if __name__ == "__main__":
    sys.exit(main())
