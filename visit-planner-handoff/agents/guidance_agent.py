"""Guidance agent for the Visit Planner.

Picks the CDC advice that applies to a visit and returns it word for word, with
sources and dates. No LLM: for medical advice, *what* CDC says is chosen by rules
and quoted exactly; the planner's composer only writes the text around it.

  1. maps who is being visited to CDC audiences and relevant pathogens
     (VISIT_PROFILES below),
  2. queries Zetaris (refdata.cdc_guidance) for matching rows,
  3. puts advice for pathogens the Activity agents flagged first,
  4. turns rows marked CHECK (e.g. infant RSV after the Jan 2026 schedule change)
     into "talk to a healthcare provider" caveats,
  5. returns the same shape as pertussis_agent: briefing, facts, sources, caveats.

Command line:
    python guidance_agent.py newborn
    python guidance_agent.py newborn --pregnant --priority pertussis rsv
    python guidance_agent.py older_adult --json
    python guidance_agent.py newborn --csv path/to/cdc_guidance.csv   # no Zetaris needed

From the planner:
    from guidance_agent import guidance_for_visit
    g = guidance_for_visit("newborn", priority=["pertussis"])
    g["briefing"], g["facts"], g["sources"], g["caveats"]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_SCRIPTS = Path(__file__).resolve().parent.parent / "getting-started" / "scripts"
sys.path.insert(0, str(REPO_SCRIPTS))

TABLE = "refdata.cdc_guidance"
COLUMNS = ["guidance_id", "pathogen", "audience", "advice", "source_title", "source_url",
           "cdc_last_reviewed", "cdc_last_updated", "retrieved", "status_note"]

# Who is being visited -> which CDC audiences and pathogens apply.
# 'respiratory' rows are general advice (stay home when sick, hand hygiene, cleaner air).
VISIT_PROFILES = {
    "newborn": {
        "label": "a newborn baby",
        "audiences": ["infant", "visitor_newborn", "visitor_any"],
        "pathogens": ["pertussis", "rsv", "influenza", "covid", "respiratory"],
    },
    "older_adult": {
        "label": "an older adult (65+)",
        "audiences": ["older_adult", "visitor_any"],
        "pathogens": ["influenza", "covid", "rsv", "respiratory"],
    },
}
PATHOGEN_NAMES = {"pertussis": "whooping cough", "rsv": "RSV", "influenza": "flu",
                  "covid": "COVID-19", "respiratory": "respiratory viruses in general"}
PROVIDER_CAVEAT = ("CDC's advice on this may have changed recently; check with a healthcare provider "
                   "about what applies.")


# --------------------------------------------------------------------------- tool: Zetaris

def _sql_list(values: list[str]) -> str:
    # Values come only from VISIT_PROFILES (a fixed vocabulary), never from user text.
    return ", ".join("'" + v.replace("'", "") + "'" for v in values)


def fetch_rows(audiences: list[str], pathogens: list[str], channel: str = "rest") -> list[dict]:
    import zetaris_sql
    zetaris_sql.load_env(str(REPO_SCRIPTS.parent / ".env.local"))
    sql = (f"SELECT {', '.join(COLUMNS)} FROM {TABLE} "
           f"WHERE audience IN ({_sql_list(audiences)}) AND pathogen IN ({_sql_list(pathogens)})")
    ch = zetaris_sql.open_channel(channel)
    try:
        rows = ch.run(sql, limit=200).rows
    finally:
        ch.close()
    return [{c: ("" if v is None else str(v)) for c, v in zip(COLUMNS, r)} for r in rows or []]


def rows_from_csv(path: str, audiences: list[str], pathogens: list[str]) -> list[dict]:
    """Offline mode for teammates without Zetaris: same filter, read from the CSV."""
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)
                if r["audience"] in audiences and r["pathogen"] in pathogens]


# --------------------------------------------------------------------------- logic

def resolve_profile(visited: str, pregnant: bool = False) -> dict:
    if visited not in VISIT_PROFILES:
        raise ValueError(f"Unknown visit type {visited!r}; use one of {sorted(VISIT_PROFILES)}")
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in VISIT_PROFILES[visited].items()}
    if pregnant:
        p["audiences"].insert(0, "pregnant")
    return p


def order_rows(rows: list[dict], pathogens: list[str], priority: list[str]) -> list[dict]:
    """Flagged pathogens first, then the profile's pathogen order, general advice last."""
    rank = {p: i for i, p in enumerate(list(dict.fromkeys(
        [p for p in priority if p in pathogens] + pathogens)))}
    return sorted(rows, key=lambda r: (rank.get(r["pathogen"], 99), r["guidance_id"]))


def build(visited: str, rows: list[dict], profile: dict, priority: list[str]) -> dict:
    rows = order_rows(rows, profile["pathogens"], priority)
    sources, caveats, lines = [], [], []
    src_ids = {}
    for r in rows:
        if r["source_url"] not in src_ids:
            src_ids[r["source_url"]] = len(src_ids) + 1
            sources.append({"id": src_ids[r["source_url"]], "title": r["source_title"],
                            "url": r["source_url"], "cdc_last_updated": r["cdc_last_updated"],
                            "retrieved": r["retrieved"]})
        n = src_ids[r["source_url"]]
        needs_check = r["status_note"].strip().upper().startswith("CHECK")
        line = f"- {r['advice']} [{n}]"
        if needs_check:
            line += f" ({PROVIDER_CAVEAT})"
            caveats.append(f"{r['guidance_id']}: {r['status_note']}")
        lines.append(line)
    flagged = [PATHOGEN_NAMES.get(p, p) for p in priority if p in profile["pathogens"]]
    head = f"What CDC recommends when visiting {profile['label']}"
    if flagged:
        head += f" (advice on {', '.join(flagged)} first, as activity is notable)"
    retrieved = max((r["retrieved"] for r in rows), default="")
    briefing = head + ":\n" + "\n".join(lines) if lines else \
        f"No matching CDC guidance rows were found for {profile['label']}."
    briefing += (f"\nThis summarises CDC guidance (pages retrieved {retrieved}); "
                 "it is not personal medical advice.")
    return {
        "agent": "guidance",
        "briefing": briefing,
        "method": "rules (no LLM)",
        "facts": {"visited": visited, "audiences": profile["audiences"],
                  "pathogens": profile["pathogens"], "priority": priority,
                  "guidance_ids": [r["guidance_id"] for r in rows],
                  "rows": rows},
        "sources": sources,
        "caveats": caveats,
    }


def guidance_for_visit(visited: str, priority: list[str] | None = None, pregnant: bool = False,
                       channel: str = "rest", csv_path: str | None = None) -> dict:
    """Main entry point for the planner."""
    priority = priority or []
    profile = resolve_profile(visited, pregnant)
    if csv_path:
        rows = rows_from_csv(csv_path, profile["audiences"], profile["pathogens"])
    else:
        rows = fetch_rows(profile["audiences"], profile["pathogens"], channel)
    return build(visited, rows, profile, priority)


def main() -> int:
    p = argparse.ArgumentParser(description="Guidance agent (CDC advice, no LLM)")
    p.add_argument("visited", choices=sorted(VISIT_PROFILES), help="who is being visited")
    p.add_argument("--pregnant", action="store_true", help="someone in the household is pregnant")
    p.add_argument("--priority", nargs="*", default=[],
                   help="pathogens flagged by the Activity agents, e.g. pertussis rsv")
    p.add_argument("--channel", choices=["rest", "jdbc"], default="rest")
    p.add_argument("--csv", help="read the guidance CSV instead of Zetaris (offline test)")
    p.add_argument("--json", action="store_true", help="print the full structured result")
    a = p.parse_args()
    try:
        res = guidance_for_visit(a.visited, a.priority, a.pregnant, a.channel, a.csv)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(res["briefing"])
    print()
    for s in res["sources"]:
        print(f"[{s['id']}] {s['title']} (CDC updated {s['cdc_last_updated']}): {s['url']}")
    if res["caveats"]:
        print("\nTo check: " + " | ".join(res["caveats"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
