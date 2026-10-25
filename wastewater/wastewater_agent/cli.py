"""Command line: ask, memory, feedback, audit, sleep, status."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .config import ConfigError, load_settings
from .hmem import HMem
from .llm import NightshiftProvider, ProviderUnauthorized
from .zetaris import JdbcClient, ZetarisError, sql


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="wastewater_agent", description="SARS-CoV-2 wastewater surveillance agent")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("ask", help="answer a natural-language question")
    a.add_argument("question")
    a.add_argument("--json", action="store_true", help="print the fact sheet and plan as JSON after the answer")

    sub.add_parser("status", help="check Zetaris, Nightshift and memory")

    m = sub.add_parser("memory", help="inspect memories")
    msub = m.add_subparsers(dest="memory_command", required=True)
    ml = msub.add_parser("list")
    ml.add_argument("--layer", choices=["short_term", "working", "long_term", "archived"])
    ms = msub.add_parser("show")
    ms.add_argument("id")

    f = sub.add_parser("feedback", help="rate a memory")
    f.add_argument("id")
    f.add_argument("kind", choices=["helpful", "not_helpful", "wrong"])

    au = sub.add_parser("audit", help="ledger entries for a memory")
    au.add_argument("id")

    s = sub.add_parser("sleep", help="preview or run the sleep cycle")
    s.add_argument("--execute", action="store_true")
    s.add_argument("--restore", metavar="BACKUP_ID")

    b = sub.add_parser("benchmark", help="score the planner, answers and memory against a question set")
    b.add_argument("--questions", help="question set JSON (default benchmark/questions.json)")
    b.add_argument("--layers", default="plan,answer,memory", help="comma list of plan,answer,memory")
    b.add_argument("--repeats", type=int, default=1, help="runs per question for the plan layer")
    b.add_argument("--no-judge", action="store_true", help="skip the meterless/judge scoring")
    b.add_argument("--out", help="results JSON path (default benchmark/results-<timestamp>.json)")

    args = p.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        if args.command == "ask":
            return cmd_ask(settings, args.question, args.json)
        if args.command == "status":
            return cmd_status(settings)
        if args.command == "benchmark":
            return cmd_benchmark(settings, args)
        hmem = HMem(settings.hmem_dir)
        if args.command == "memory":
            return cmd_memory(hmem, args)
        if args.command == "feedback":
            return cmd_feedback(hmem, args.id, args.kind)
        if args.command == "audit":
            return cmd_audit(hmem, args.id)
        if args.command == "sleep":
            return cmd_sleep(hmem, args.execute, args.restore)
    except ProviderUnauthorized as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ZetarisError as e:
        print(f"error: zetaris: {e}", file=sys.stderr)
        return 1
    return 2


# -- commands ------------------------------------------------------------------


def cmd_ask(settings, question: str, as_json: bool) -> int:
    from .agent import Agent

    agent = Agent(settings)
    try:
        answer = agent.ask(question)
    finally:
        agent.close()
    facts = answer.facts
    print(answer.text)
    print()
    print(f"window:   {facts.window} ({facts.window.label})")
    if facts.prior_window:
        print(f"prior:    {facts.prior_window}")
    if facts.fallback_window:
        print(f"fallback: {facts.fallback_window} (most recent 7 days with data)")
    print(f"coverage: {facts.coverage}  (latest sample {facts.latest_sample_date})")
    rows = f"samples={facts.samples} positives={facts.positives} sites={facts.sites}"
    if facts.prior_samples is not None:
        rows += f" | prior samples={facts.prior_samples} positives={facts.prior_positives}"
    if facts.fallback_samples is not None:
        rows += f" | fallback samples={facts.fallback_samples} positives={facts.fallback_positives}"
    print(f"rows:     {rows}")
    print(f"plan:     intent={answer.plan.intent} state={answer.plan.state or 'us'} source={answer.plan.source}")
    for n in answer.plan.notes:
        print(f"  note: {n}")
    print("sql:")
    for i, stmt in enumerate(answer.statements, 1):
        print(f"  {i}. {stmt}")
    used = ", ".join(m.id for m in answer.memories_used) or "none"
    print(f"memories used: {used}")
    if answer.memory:
        print(f"memory stored: {answer.memory.id}")
    for c in answer.conflicts:
        print(f"conflict: {c['incomingId']} vs {c['existingId']} ({c['reason']}); resolved={c['resolved']}")
    if answer.completions:
        for c in answer.completions:
            cache = (c.raw.get("receipt") or {}).get("cache") or {}
            extra = f"  cache={cache.get('status')} reclaimed={cache.get('losers_reclaimed')}" if cache else ""
            print(f"receipt: {c.receipt_id or 'n/a'} via {c.routed_model or 'unknown'}{extra}")
    else:
        print("receipt: none")
    print(f"provider: {answer.provider}")
    for r in answer.fallback_reasons:
        print(f"  note: {r}")
    if as_json:
        print(json.dumps({"plan": answer.plan.to_dict(), "factSheet": facts.to_dict(),
                          "retrieval": answer.retrieval_reason}, indent=1))
    return 0


def cmd_status(settings) -> int:
    ok = True
    print("zetaris:")
    client = JdbcClient(settings)
    try:
        client.query(sql.ping())
        rows = client.query(sql.latest_sample_date())
        latest = rows[0].get("latest_sample_date") if rows else None
        print(f"  ok  {settings.zetaris_jdbc_url}  latest sample {latest}")
    except ZetarisError as e:
        ok = False
        print(f"  FAIL {e}")
    finally:
        client.close()

    print("nightshift:")
    ns = NightshiftProvider(settings.nightshift_base_url, settings.nightshift_token)
    state, models = ns.readiness()
    print(f"  {state}  {settings.nightshift_base_url}  token from {settings.nightshift_token_source}")
    for m in models:
        if str(m["id"]).startswith("meterless/") and m["availability"] in ("ready", "cloud"):
            print(f"    {m['id']:<20} availability={m['availability']}")
    owners: dict[str, int] = {}
    for m in models:
        if not str(m["id"]).startswith("meterless/"):
            owners[str(m["owned_by"])] = owners.get(str(m["owned_by"]), 0) + 1
    if owners:
        print("    routed owners: " + ", ".join(f"{k} ({n})" for k, n in sorted(owners.items())))
    if state == "unauthorized":
        ok = False

    print("memory:")
    hmem = HMem(settings.hmem_dir)
    for layer, n in hmem.counts().items():
        print(f"  {layer:<10} {n}")
    print(f"  dir        {settings.hmem_dir}")
    return 0 if ok else 1


def cmd_benchmark(settings, args) -> int:
    from datetime import datetime, timezone
    from pathlib import Path

    from .benchmark import DEFAULT_QUESTIONS, Benchmark, load_questions, print_summary
    from .config import AGENT_ROOT

    qpath = Path(args.questions) if args.questions else DEFAULT_QUESTIONS
    questions = load_questions(qpath)
    layers = [l.strip() for l in args.layers.split(",") if l.strip()]
    bench = Benchmark(settings, questions, layers=layers, repeats=args.repeats, judge=not args.no_judge)
    print(f"benchmark: {len(questions)} questions from {qpath}  layers={','.join(bench.layers)}  repeats={bench.repeats}")
    report = bench.run()
    print_summary(report)
    out = Path(args.out) if args.out else AGENT_ROOT / "benchmark" / f"results-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"results: {out}")
    return 0


def cmd_memory(hmem: HMem, args) -> int:
    if args.memory_command == "list":
        recs = hmem.list(args.layer)
        if not recs:
            print("no memories")
            return 0
        for r in recs:
            flag = f" supersededBy={r.supersededBy}" if r.supersededBy else ""
            print(f"{r.id}  {r.layer:<9} conf={r.confidence:.2f} acc={r.accessCount}  {r.createdAt}{flag}")
            print(f"    {r.content}")
        return 0
    rec = hmem.show(args.id)
    if rec is None:
        print(f"no memory {args.id}", file=sys.stderr)
        return 1
    data = rec.to_dict()
    data["embedding"] = f"<{len(rec.embedding or [])} dims>"
    print(json.dumps(data, indent=1, ensure_ascii=False))
    return 0


def cmd_feedback(hmem: HMem, memory_id: str, kind: str) -> int:
    try:
        rec = hmem.feedback(memory_id, kind)
    except KeyError:
        print(f"no memory {memory_id}", file=sys.stderr)
        return 1
    print(f"{rec.id}: {kind} -> confidence {rec.confidence:.2f}, accessCount {rec.accessCount}, tags {rec.tags}")
    return 0


def cmd_audit(hmem: HMem, memory_id: str) -> int:
    entries = hmem.audit(memory_id)
    if not entries:
        print(f"no ledger entries for {memory_id}")
        return 0
    for e in entries:
        line = f"{e['timestamp']}  {e['action']:<18} actor={e['actor']}"
        if e.get("details"):
            line += "  " + json.dumps(e["details"], ensure_ascii=False)
        print(line)
        if "previousState" in e or "newState" in e:
            print(f"    {json.dumps(e.get('previousState'))} -> {json.dumps(e.get('newState'))}")
    return 0


def cmd_sleep(hmem: HMem, execute: bool, restore: str | None) -> int:
    if restore:
        try:
            print(json.dumps(hmem.sleep_restore(restore), indent=1))
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    if execute:
        print(json.dumps(hmem.sleep_execute(), indent=1))
        return 0
    print(json.dumps(hmem.sleep_preview(), indent=1))
    return 0


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)
