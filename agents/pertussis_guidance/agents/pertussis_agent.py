"""Pertussis Activity agent for the Visit Planner.

Given the US state(s) a visit starts and ends in, it:
  1. queries Zetaris (visitplanner.pertussis_state_rates) for every state,
  2. turns the numbers into plain facts (this year vs last year, vs the national rate,
     small numbers, missing data),
  3. writes a safe template paragraph, then asks the LLM (Meterless Nightshift,
     OpenAI-compatible) to polish it without changing any number or citation,
  4. checks the result twice: rules first (every number must come from the facts, no risk
     scores, sources cited), then a second LLM acting as a reviewer (same meaning as the
     template? caveats kept? no advice or reassurance?),
  5. feeds any problems back to the writer for up to 2 retries, then falls back to the
     template, so the output is always safe.

It never gives a personal risk score: it summarises official surveillance data.

Use it from the command line:
    python3 pertussis_agent.py AZ CA            # visit from Arizona to California
    python3 pertussis_agent.py Arizona --no-llm # template only, no model call
    python3 pertussis_agent.py AZ --json        # full structured output for the planner
    python3 pertussis_agent.py AZ CA --no-llm --csv pertussis_state_2026w41.csv  # no Zetaris

Or from the planner:
    from pertussis_agent import pertussis_activity
    result = pertussis_activity(["AZ", "CA"])
    result["briefing"], result["facts"], result["sources"]

Settings (in getting-started/.env.local):
    ZETARIS_*            already set up; the REST channel needs ZETARIS_API_KEY
    METERLESS_BASE_URL   e.g. http://127.0.0.1:8088/v1  (shown in the Nightshift app)
    METERLESS_API_KEY    the runtime token from the Nightshift app
    METERLESS_MODEL      default meterless/fast
    METERLESS_APP        optional value for the meterless-app header
    METERLESS_EVAL_MODEL optional different model for the reviewer (default: same model)
    METERLESS_TTFB_MS    how long Nightshift waits for a first token (default 240000, max 300000)
    METERLESS_REASONING_EFFORT  optional, e.g. low, to cut a reasoning model's thinking time
    METERLESS_MAX_TOKENS default 600
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Reuse the getting-started repo's Zetaris client (it also loads .env.local).
REPO_SCRIPTS = Path(__file__).resolve().parent.parent / "getting-started" / "scripts"
sys.path.insert(0, str(REPO_SCRIPTS))
try:
    import zetaris_sql  # noqa: E402  (from the zetaris/getting-started repo)
    # Load getting-started/.env.local (Zetaris and Meterless settings) into the environment.
    zetaris_sql.load_env(str(REPO_SCRIPTS.parent / ".env.local"))
except ImportError:  # offline use (--csv) without the getting-started repo
    zetaris_sql = None

VIEW = "visitplanner.pertussis_state_rates"
COLUMNS = ["state", "mmwr_week", "ytd_cases", "prev_ytd_cases", "population_2025",
           "ytd_rate_per_100k", "prev_ytd_rate_per_100k", "ratio_vs_last_year", "data_ok"]

SOURCES = [
    {"id": 1, "title": "CDC NNDSS Weekly Data (provisional), pertussis",
     "url": "https://data.cdc.gov/Public-Health-Surveillance/NNDSS-Weekly-Data/x9gk-5huc"},
    {"id": 2, "title": "US Census Bureau, Vintage 2025 state population estimates",
     "url": "https://www.census.gov/data/datasets/time-series/demo/popest/2020s-state-total.html"},
]

STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

SMALL_NUMBERS = 20      # fewer cases than this this year -> rates and ratios are unstable
SIMILAR_BAND = (0.9, 1.1)  # ratio vs last year treated as "about the same"


# --------------------------------------------------------------------------- tool: Zetaris

def _num(x):
    """Zetaris REST returns strings/numbers, JDBC may return Java objects."""
    if x is None or str(x).strip() in ("", "None", "null"):
        return None
    try:
        return float(str(x))
    except ValueError:
        return None


def _bool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "t")


def fetch_rows(channel: str = "rest") -> list[dict]:
    """Tool call: read every state row from the Zetaris view (52 rows, so fetch all)."""
    if zetaris_sql is None:
        raise RuntimeError("getting-started/scripts not found next to this folder; clone "
                           "zetaris/getting-started there, or use --csv for offline mode.")
    sql = f"SELECT {', '.join(COLUMNS)} FROM {VIEW}"
    ch = zetaris_sql.open_channel(channel)
    try:
        rows = ch.run(sql, limit=200).rows
    finally:
        ch.close()
    if not rows:
        raise RuntimeError(f"No rows returned from {VIEW}. Run it in the SQL Workspace to check.")
    out = []
    for r in rows:
        d = dict(zip(COLUMNS, r))
        out.append({
            "state": str(d["state"]),
            "mmwr_week": int(_num(d["mmwr_week"]) or 0),
            "ytd_cases": _num(d["ytd_cases"]),
            "prev_ytd_cases": _num(d["prev_ytd_cases"]),
            "population_2025": _num(d["population_2025"]),
            "ytd_rate_per_100k": _num(d["ytd_rate_per_100k"]),
            "prev_ytd_rate_per_100k": _num(d["prev_ytd_rate_per_100k"]),
            "ratio_vs_last_year": _num(d["ratio_vs_last_year"]),
            "data_ok": _bool(d["data_ok"]),
        })
    return out


# --------------------------------------------------------------------------- reasoning

def resolve_state(text: str) -> str:
    t = text.strip()
    if t.upper() in STATE_ABBR:
        return STATE_ABBR[t.upper()]
    for name in STATE_ABBR.values():
        if name.lower() == t.lower():
            return name
    raise ValueError(f"Unknown US state: {text!r}")


def national(rows: list[dict]) -> dict:
    """National rate from states with complete data (excludes Puerto Rico)."""
    ok = [r for r in rows if r["data_ok"] and r["state"] != "Puerto Rico"
          and r["ytd_cases"] is not None and r["population_2025"]]
    cases = sum(r["ytd_cases"] for r in ok)
    prev = sum(r["prev_ytd_cases"] for r in ok)
    pop = sum(r["population_2025"] for r in ok)
    return {
        "ytd_cases": int(cases),
        "prev_ytd_cases": int(prev),
        "ytd_rate_per_100k": round(cases / pop * 1e5, 2),
        "ratio_vs_last_year": round(cases / prev, 2) if prev else None,
        "states_included": len(ok),
    }


def state_facts(r: dict, nat: dict) -> dict:
    f = {"state": r["state"], "mmwr_week": r["mmwr_week"], "data_ok": r["data_ok"], "notes": []}
    if not r["data_ok"] or r["ytd_cases"] is None:
        f["notes"].append("CDC has no complete count for this state this year "
                          "(not submitted or unavailable); this is a reporting gap, "
                          "not evidence of zero cases.")
        f["trend"] = "unknown"
        f["vs_national"] = "unknown"
        return f
    f.update({
        "ytd_cases": int(r["ytd_cases"]),
        "prev_ytd_cases": int(r["prev_ytd_cases"]) if r["prev_ytd_cases"] is not None else None,
        "ytd_rate_per_100k": r["ytd_rate_per_100k"],
        "ratio_vs_last_year": r["ratio_vs_last_year"],
    })
    ratio = r["ratio_vs_last_year"]
    if ratio is None:
        f["trend"] = "unknown"
    elif ratio > SIMILAR_BAND[1]:
        f["trend"] = "higher than at this point last year"
    elif ratio < SIMILAR_BAND[0]:
        f["trend"] = "lower than at this point last year"
    else:
        f["trend"] = "about the same as at this point last year"
    rel = r["ytd_rate_per_100k"] / nat["ytd_rate_per_100k"] if nat["ytd_rate_per_100k"] else None
    f["rate_vs_national_x"] = round(rel, 1) if rel is not None else None
    if rel is None:
        f["vs_national"] = "unknown"
    elif rel >= 1.5:
        f["vs_national"] = "above the national rate"
    elif rel <= 0.67:
        f["vs_national"] = "below the national rate"
    else:
        f["vs_national"] = "close to the national rate"
    if r["ytd_cases"] < SMALL_NUMBERS:
        f["notes"].append(f"Small numbers ({int(r['ytd_cases'])} cases this year), "
                          "so the rate and the comparison with last year are unstable.")
    return f


GENERAL_CAVEATS = [
    "Counts are provisional and reported by state; recent weeks are often revised upward as late reports arrive.",
    "These are state-wide figures and do not describe a particular city, household or person.",
]


# --------------------------------------------------------------------------- LLM (Meterless)

SYSTEM_PROMPT = """You edit one short section of a visit-planning briefing about whooping cough (pertussis).
You are given FACTS (JSON) and a DRAFT paragraph that is already correct.
Rewrite the DRAFT so it reads naturally for a family member planning a visit. Rules:
- Keep every number exactly as it appears in the DRAFT (same digits, same decimals, same commas). Do not add,
  round, combine or calculate any number. Do not mention any number that is not in the DRAFT.
- Keep the citations [1] and [2] after the sentences that use them.
- Keep every caveat (provisional counts, missing data, small numbers).
- 3 to 5 sentences. No headings, no bullet points.
- Never give a risk score, a percentage, a probability or medical advice. Do not discuss vaccination.
Return only the rewritten paragraph."""


def llm_facts(facts: dict) -> dict:
    """The small subset the model needs (fewer numbers to mangle)."""
    keep = ("state", "ytd_cases", "prev_ytd_cases", "ytd_rate_per_100k", "trend", "vs_national", "notes")
    return {
        "pathogen": facts["pathogen"],
        "as_of_mmwr_week": facts["as_of_mmwr_week"],
        "national_rate_per_100k": facts["national"]["ytd_rate_per_100k"],
        "states": [{k: f[k] for k in keep if k in f} for f in facts["states"]],
    }


def call_llm(messages: list[dict], model: str | None = None) -> str:
    base = os.environ.get("METERLESS_BASE_URL", "").rstrip("/")
    key = os.environ.get("METERLESS_API_KEY", "")
    if not base or not key:
        raise RuntimeError("Set METERLESS_BASE_URL and METERLESS_API_KEY in .env.local.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if os.environ.get("METERLESS_APP"):
        headers["meterless-app"] = os.environ["METERLESS_APP"]
        headers["meterless-scope"] = "user"
    # Cloud models can be slow to start: tell Nightshift how long to wait for the first
    # token (its header allows up to 300000 ms) and wait a bit longer ourselves.
    ttfb_ms = int(os.environ.get("METERLESS_TTFB_MS", "240000"))
    headers["meterless-ttfb-ms"] = str(ttfb_ms)
    body = {
        "model": model or os.environ.get("METERLESS_MODEL", "meterless/fast"),
        "temperature": 0.1,
        "max_tokens": int(os.environ.get("METERLESS_MAX_TOKENS", "600")),
        # Nemotron routes honour this and answer without a reasoning preamble; without it
        # the hidden reasoning leaks into the content and the number check rejects it.
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": messages,
    }
    if os.environ.get("METERLESS_REASONING_EFFORT"):  # e.g. low: less hidden "thinking" first
        body["reasoning_effort"] = os.environ["METERLESS_REASONING_EFFORT"]
    req = Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                  headers=headers, method="POST")
    try:
        with urlopen(req, timeout=ttfb_ms / 1000 + 90) as resp:
            out = json.loads(resp.read().decode())
    except HTTPError as e:
        raise RuntimeError(f"Meterless HTTP {e.code}: {e.read(1500).decode(errors='replace')}") from e
    except (URLError, OSError) as e:
        raise RuntimeError(f"Cannot reach Meterless at {base}: {getattr(e, 'reason', e)}") from e
    return out["choices"][0]["message"]["content"].strip()


EVAL_PROMPT = """You are a strict reviewer for a public-health briefing. You are given FACTS (JSON),
the REFERENCE paragraph (correct) and a CANDIDATE paragraph (a rewrite of the reference).
Check the CANDIDATE against the REFERENCE and FACTS:
1. Every trend says the same thing (higher/lower/about the same as last year; above/below/close to the national rate).
2. It does not mix up which numbers belong to which state.
3. Every caveat in the REFERENCE is still there (provisional counts, missing data, small numbers).
4. It adds no new claims, advice, vaccination talk, risk scores or reassurance (e.g. "safe", "nothing to worry about").
5. It is clear, plain English.
Answer in this exact format:
VERDICT: PASS or FAIL
ISSUES:
- one line per problem (write "- none" if PASS)"""


def evaluate(facts: dict, reference: str, candidate: str) -> dict:
    """Second LLM call that reviews meaning, which the rule checker cannot see.
    Model: METERLESS_EVAL_MODEL if set, else the writer's model."""
    model = os.environ.get("METERLESS_EVAL_MODEL") or None
    raw = call_llm([
        {"role": "system", "content": EVAL_PROMPT},
        {"role": "user", "content": "FACTS:\n" + json.dumps(llm_facts(facts), indent=2)
                                    + "\n\nREFERENCE:\n" + reference
                                    + "\n\nCANDIDATE:\n" + candidate},
    ], model=model)
    m = re.search(r"VERDICT\W*(PASS|FAIL)", raw, re.I)
    verdict = m.group(1).upper() if m else "UNCLEAR"
    issues = [ln.strip("-* ").strip() for ln in raw.split("ISSUES", 1)[-1].splitlines()
              if ln.strip().startswith(("-", "*")) and ln.strip("-* ").strip().lower() not in ("none", "")]
    if verdict == "PASS":
        issues = []
    elif verdict == "FAIL" and not issues:
        issues = ["evaluator failed the draft without giving a reason"]
    return {"verdict": verdict, "issues": issues, "model": model or os.environ.get("METERLESS_MODEL"),
            "raw": raw}


def llm_briefing(facts: dict, draft: str, max_tries: int = 3, use_evaluator: bool = True) -> tuple:
    """Ask the model to polish the template; feed checker problems back for a retry.
    A draft must pass the rule checks and then the reviewer model (evaluate()).
    Returns (accepted_text_or_None, problems_of_last_try, rejected_drafts, last_evaluation)."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "FACTS:\n" + json.dumps(llm_facts(facts), indent=2)
                                    + "\n\nDRAFT:\n" + draft},
    ]
    rejected, problems, evaluation = [], [], None
    for _ in range(max_tries):
        text = call_llm(messages)
        problems = check_briefing(text, facts, draft)
        if not problems and use_evaluator:
            evaluation = evaluate(facts, draft, text)
            if evaluation["verdict"] == "FAIL":
                problems = ["reviewer: " + i for i in evaluation["issues"]]
        if not problems:
            return text, [], rejected, evaluation
        rejected.append({"text": text, "problems": problems})
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "That version has problems: " + "; ".join(problems)
             + ". Fix them. Use only numbers that appear in the DRAFT, exactly as written, "
               "keep the [1] and [2] citations and keep the same meaning as the DRAFT. "
               "Return only the paragraph."},
        ]
    return None, problems, rejected, evaluation


# --------------------------------------------------------------------------- checks

BANNED = re.compile(r"risk score|\b\d+(\.\d+)?\s*%|percent chance|probability|likelihood of (getting|catching)",
                    re.I)


NUMBER = re.compile(r"(?<![\w.\[])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w\]])")


def numbers_in(text: str) -> list[str]:
    return [_fmt(float(m.replace(",", ""))) for m in NUMBER.findall(text)]


def allowed_numbers(facts: dict, draft: str = "") -> set[str]:
    nums = set(numbers_in(draft))

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            nums.add(_fmt(x))
        elif isinstance(x, str):
            nums.update(numbers_in(x))
    walk(facts)
    return nums | {"1", "2", "100000", "2025", "2026"}  # citations, "per 100,000", years


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(round(float(x), 2))


def check_briefing(text: str, facts: dict, draft: str = "") -> list[str]:
    problems = []
    if BANNED.search(text):
        problems.append("contains a risk score, percentage or probability")
    if "[1]" not in text:
        problems.append("does not cite the CDC source [1]")
    allowed = allowed_numbers(facts, draft)
    for n in numbers_in(text):
        if n not in allowed:
            problems.append(f"number {n} is not in the facts")
    for f in facts["states"]:
        if f["state"] not in text:
            problems.append(f"does not mention {f['state']}")
    return problems


# --------------------------------------------------------------------------- template fallback

def template_briefing(facts: dict) -> str:
    nat = facts["national"]
    parts = []
    for f in facts["states"]:
        if f["trend"] == "unknown" and "ytd_cases" not in f:
            parts.append(f"CDC does not have a complete whooping cough count for {f['state']} "
                         f"this year, so we cannot say how it compares [1].")
            continue
        s = (f"{f['state']} has reported {f['ytd_cases']} whooping cough cases so far this year "
             f"({f['ytd_rate_per_100k']} per 100,000 people), {f['trend']} "
             f"({f['prev_ytd_cases']} cases) [1][2].")
        if f.get("rate_vs_national_x") is not None:
            s += f" That is {f['vs_national']} of {nat['ytd_rate_per_100k']} per 100,000 [1][2]."
        parts.append(s)
        parts += [n for n in f["notes"]]
    parts.append(f"Figures are provisional CDC counts up to week {facts['as_of_mmwr_week']} "
                 "of 2026 and are often revised as late reports arrive [1].")
    return " ".join(parts)


# --------------------------------------------------------------------------- agent

def rows_from_csv(path: str) -> list[dict]:
    """Offline mode: read the pertussis_state_rates snapshot CSV instead of Zetaris."""
    with open(path, newline="", encoding="utf-8") as fh:
        return [{
            "state": r["state"], "mmwr_week": int(_num(r.get("mmwr_week")) or 0),
            "ytd_cases": _num(r["ytd_cases"]), "prev_ytd_cases": _num(r["prev_ytd_cases"]),
            "population_2025": _num(r["population_2025"]),
            "ytd_rate_per_100k": _num(r["ytd_rate_per_100k"]),
            "prev_ytd_rate_per_100k": _num(r["prev_ytd_rate_per_100k"]),
            "ratio_vs_last_year": _num(r["ratio_vs_last_year"]), "data_ok": _bool(r["data_ok"]),
        } for r in csv.DictReader(fh)]


def pertussis_activity(states: list[str], use_llm: bool = True, channel: str = "rest",
                       rows: list[dict] | None = None, use_evaluator: bool = True,
                       csv_path: str | None = None) -> dict:
    """Main entry point for the planner. `rows` or `csv_path` skip Zetaris (tests/offline)."""
    names = list(dict.fromkeys(resolve_state(s) for s in states))
    if rows is None and csv_path:
        rows = rows_from_csv(csv_path)
    rows = rows if rows is not None else fetch_rows(channel)
    by_state = {r["state"]: r for r in rows}
    nat = national(rows)
    facts = {
        "pathogen": "pertussis (whooping cough)",
        "as_of_mmwr_week": max(r["mmwr_week"] for r in rows),
        "national": nat,
        "states": [state_facts(by_state[n], nat) if n in by_state
                   else {"state": n, "trend": "unknown", "vs_national": "unknown",
                         "data_ok": False, "notes": ["State not found in the CDC table."]}
                   for n in names],
        "general_caveats": GENERAL_CAVEATS,
    }
    draft = template_briefing(facts)
    briefing, method, problems, rejected, evaluation = draft, "template", [], [], None
    if use_llm:
        try:
            text, problems, rejected, evaluation = llm_briefing(facts, draft, use_evaluator=use_evaluator)
            if text:
                review = f", reviewer: {evaluation['verdict']}" if evaluation else ", no reviewer"
                briefing, method = text, f"llm (attempt {len(rejected) + 1}{review})"
        except RuntimeError as e:
            problems = [str(e)]
    return {"agent": "pertussis_activity", "briefing": briefing, "method": method,
            "check_problems": problems, "rejected_drafts": rejected, "evaluation": evaluation,
            "facts": facts, "sources": SOURCES}


def main() -> int:
    p = argparse.ArgumentParser(description="Pertussis Activity agent")
    p.add_argument("states", nargs="+", help="US states (names or 2-letter codes), start then end")
    p.add_argument("--no-llm", action="store_true", help="use the template, skip Meterless")
    p.add_argument("--channel", choices=["rest", "jdbc"], default="rest")
    p.add_argument("--json", action="store_true", help="print the full structured result")
    p.add_argument("--show-drafts", action="store_true", help="print LLM drafts the checker rejected")
    p.add_argument("--no-review", action="store_true", help="skip the second (reviewer) LLM call")
    p.add_argument("--csv", help="read a pertussis_state_rates CSV snapshot instead of Zetaris")
    a = p.parse_args()
    try:
        res = pertussis_activity(a.states, use_llm=not a.no_llm, channel=a.channel,
                                 use_evaluator=not a.no_review, csv_path=a.csv)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(res["briefing"])
    print()
    for s in res["sources"]:
        print(f"[{s['id']}] {s['title']}: {s['url']}")
    print(f"\n(written by: {res['method']})")
    if res["check_problems"]:
        print("LLM draft rejected or unavailable: " + "; ".join(res["check_problems"]))
    if a.show_drafts and res["evaluation"]:
        print(f"\n--- reviewer's last answer:\n{res['evaluation']['raw']}")
    if a.show_drafts:
        for i, d in enumerate(res["rejected_drafts"], 1):
            print(f"\n--- rejected draft {i}: {'; '.join(d['problems'])}\n{d['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
