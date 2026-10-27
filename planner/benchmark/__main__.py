"""python -m planner.benchmark [--layers rules,compose,e2e] [--repeats N] [--out FILE]"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from wastewater_agent.config import load_settings

from .run import DEFAULT_LAYERS, HERE, LAYERS, Benchmark, print_summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="planner.benchmark", description="Score the planner's rules, composer and evaluator")
    p.add_argument("--layers", default=",".join(DEFAULT_LAYERS),
                   help=f"comma list of {','.join(LAYERS)} (default {','.join(DEFAULT_LAYERS)}; e2e takes about 10 minutes)")
    p.add_argument("--repeats", type=int, default=1, help="compose runs per trip, to see run-to-run variance")
    p.add_argument("--weather-url", help="weather service base URL for e2e (default http://127.0.0.1:8770)")
    p.add_argument("--out", help="results JSON path (default planner/benchmark/results-<timestamp>.json)")
    a = p.parse_args(argv)
    layers = [l.strip() for l in a.layers.split(",") if l.strip()]
    unknown = [l for l in layers if l not in LAYERS]
    if unknown:
        raise SystemExit(f"unknown layer(s) {unknown}; use {', '.join(LAYERS)}")

    bench = Benchmark(load_settings(), layers=layers, repeats=a.repeats, weather_url=a.weather_url)
    print(f"planner benchmark: layers={','.join(bench.layers)}  repeats={bench.repeats}  trips={len(bench.fixtures)}")
    report = bench.run()
    print_summary(report)
    out = Path(a.out) if a.out else HERE / f"results-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(report.to_dict(), indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nresults: {out}")
    return 0 if all(r.ok for r in report.rules) else 1


if __name__ == "__main__":
    sys.exit(main())
