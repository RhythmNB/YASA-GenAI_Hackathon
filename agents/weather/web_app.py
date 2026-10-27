"""Local web app for the Weather agent: a chat page at http://127.0.0.1:8766

Runs on your own computer only. The page sends each question to this program,
which works out the city (any of ~200 US cities) and days, runs the Weather agent through the demo
Planner + Evaluator, and sends back the hand-off for the page to display.

Messages starting with "remember" are saved to H-MEM as household facts,
for example: "remember Dad is 85 and uses a walking frame".

Usage:  python web_app.py            (then open http://127.0.0.1:8766)
"""
import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cities import CITIES, resolve_city
from demo_planner import plan_visit
from hmem import MemoryStoreService
from llm import llm_mode
from risk import SENSITIVE_GROUPS, detect_travellers
from cities import get_city
from tracing import Tracer

HOST, PORT = "127.0.0.1", 8766
HERE = Path(__file__).resolve().parent
PAGE = HERE / "web" / "index.html"
HOUSEHOLD = "household"

def parse_question(text):
    """Planner step: pull the city and number of days out of a question."""
    t = text.lower()
    city, note = resolve_city(text)
    weekdays = None
    m = re.search(r"\b(\d{1,2})\s*days?\b", t)
    if m:
        days = int(m.group(1))
    elif "today" in t or "tonight" in t:
        days = 1
    elif "tomorrow" in t:
        days = 2
    elif "weekend" in t:
        days, weekdays = 7, ["Saturday", "Sunday"]
    elif "week" in t:
        days = 7
    else:
        days = 3
    named = [d for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
             if re.search(rf"\b{d}\b", t)]
    if named and not weekdays:
        days, weekdays = 7, [d.capitalize() for d in named]
    return city, max(1, min(days, 7)), note, weekdays


def answer(question):
    q = question.strip()
    if not q:
        return {"kind": "error", "text": "Type a question first."}

    if re.match(r"^\s*remember\b", q, re.I):
        fact = re.sub(r"^\s*remember( that)?\s*", "", q, flags=re.I).strip(" .")
        if not fact:
            return {"kind": "error", "text": "What should I remember?"}
        tracer = Tracer()
        MemoryStoreService(tracer=tracer).add(
            fact, tier="long", source="user", confidence=1.0,
            entities=[HOUSEHOLD], tags=["household"])
        return {"kind": "remembered", "text": f"Saved to household memory: {fact}",
                "run_id": tracer.run_id}

    city, days, note, weekdays = parse_question(q)
    if not city:
        return {"kind": "clarify",
                "text": f"Which US city? I have forecasts for {len(CITIES)} cities: the 50 largest "
                        "plus at least the 4 biggest in every state (e.g. 'Portland, ME' or 'Boise')."}

    travellers = detect_travellers(q)  # only what the user actually said
    tracer = Tracer()
    tracer.event("user_question", question=q, parsed_city=city, parsed_days=days, travellers=travellers)
    msg, issues = plan_visit(city, days, HOUSEHOLD, None, tracer, travellers, weekdays)
    return {"kind": "weather", "question": q, "city": city, "days": days, "note": note,
            "weekdays": weekdays,
            "handoff": msg, "evaluator": {"ok": not issues, "issues": issues},
            "mode": llm_mode(), "trace": tracer.path.name}


def weather_api(payload):
    """Structured entry point for other agents and front ends.

    payload keys (all optional except a city or question):
      city        "Portland, ME", "NYC", or free text like "portland maine"
      question    free text; city, days, weekdays and travellers are read from it if not given
      days        1-7 (default 3)
      weekdays    e.g. ["Saturday", "Sunday"]
      travellers  stated sensitive groups: older_adult, infant, young_child, pregnant, health_condition
      household   memory key for household facts (default "household")
      remember    list of household facts to store in H-MEM before answering
    Returns (http_status, body).
    """
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "send a JSON object"}
    question = str(payload.get("question") or "")
    note = None
    parsed_city, parsed_days, parsed_note, parsed_weekdays = parse_question(question) if question else (None, 3, None, None)

    city = None
    if payload.get("city"):
        info = get_city(payload["city"])
        if info:
            city = info["id"]
        else:
            city, note = resolve_city(str(payload["city"]))
    else:
        city, note = parsed_city, parsed_note
    if not city:
        return 400, {"ok": False, "error": "unknown or missing city",
                     "hint": "use an id like 'Boston, MA' (GET /api/cities lists them)"}

    try:
        days = int(payload.get("days") or parsed_days or 3)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "days must be a number 1-7"}
    days = max(1, min(days, 7))
    weekdays = payload.get("weekdays") or parsed_weekdays
    if weekdays and not isinstance(weekdays, list):
        return 400, {"ok": False, "error": "weekdays must be a list like [\"Saturday\", \"Sunday\"]"}

    travellers = payload.get("travellers")
    if travellers is None:
        travellers = detect_travellers(question)
    unknown = [t for t in travellers if t not in SENSITIVE_GROUPS]
    if unknown:
        return 400, {"ok": False, "error": f"unknown traveller groups {unknown}",
                     "allowed": sorted(SENSITIVE_GROUPS)}

    household = str(payload.get("household") or HOUSEHOLD)
    remember = [str(f) for f in (payload.get("remember") or []) if str(f).strip()]

    tracer = Tracer()
    tracer.event("api_request", payload=payload, city=city, days=days, weekdays=weekdays,
                 travellers=travellers)
    msg, issues = plan_visit(city, days, household, remember, tracer, travellers, weekdays)
    return 200, {"ok": msg.get("status") == "ok", "note": note, "handoff": msg,
                 "evaluator": {"ok": not issues, "issues": issues}, "trace": tracer.path.name}


def city_list():
    return [{"id": c["id"], "name": c["name"], "state": c["state"], "state_name": c["state_name"],
             "lat": c["lat"], "lon": c["lon"]} for c in CITIES.values()]


def memories():
    store = MemoryStoreService()
    recs = sorted(store.active(), key=lambda r: r.created_at, reverse=True)
    return [{"content": r.content, "tier": r.tier, "source": r.source,
             "created_at": r.created_at} for r in recs[:60]]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Lets a front end on another local port (e.g. the team app) call this API.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/memory":
            self._send(200, {"memories": memories()})
        elif self.path == "/api/status":
            self._send(200, {"mode": llm_mode(), "cities": len(CITIES)})
        elif self.path == "/api/cities":
            self._send(200, {"cities": city_list()})
        else:
            self._send(404, {"error": "not found"})

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_POST(self):
        if self.path not in ("/api/ask", "/api/weather"):
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/weather":
                return self._send(*weather_api(body))
            self._send(200, answer(str(body.get("question", ""))))
        except Exception as exc:  # show the problem in the page instead of hanging
            self._send(500, {"kind": "error", "text": f"Something went wrong: {exc}"})

    def log_message(self, fmt, *args):
        print("[web]", fmt % args)


def main():
    import argparse
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("WEATHER_PORT", PORT)))
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    server = ThreadingHTTPServer((HOST, args.port), Handler)
    url = f"http://{HOST}:{args.port}"
    print(f"Weather Visit Planner running at {url}  (model mode: {llm_mode()})")
    print("Close this window to stop it.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server.serve_forever()


if __name__ == "__main__":
    main()
