"""Planner agent: runs the four agents in parallel, has the Evaluator review what
came back, asks again where the Evaluator says it should (one round at most),
then hands the findings to the composer."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from wastewater_agent.agent import Agent
from wastewater_agent.config import Settings, load_settings
from wastewater_agent.llm import ProviderUnauthorized

from . import evaluator, geocode
from .adapters import guidance, pertussis, wastewater, weather
from .composer import compose
from .findings import Finding, TravelPlan, failed
from .trip import TripRequest

Progress = Callable[[dict[str, Any]], None]
TIMEOUTS = {"wastewater": 240.0, "pertussis_guidance": 120.0, "weather": 180.0}
SOURCES_OF = {"wastewater": ("covid", "flu"), "pertussis_guidance": ("pertussis", "guidance"), "weather": ("weather",)}
MAX_REPLANS = 1   # rounds in which the Evaluator may send the planner back to the agents
PATHOGEN_OF = {"covid": "sars-cov-2", "flu": "flu-a"}


class PlannerAgent:
    def __init__(self, settings: Settings | None = None, *, agent: Agent | None = None,
                 weather_url: str | None = None) -> None:
        self.settings = settings or load_settings()
        self.agent = agent or Agent(self.settings)
        self.weather_url = weather_url

    def run(self, trip: TripRequest, progress: Progress | None = None) -> TravelPlan:
        emit: Progress = progress or (lambda e: None)
        t0 = time.perf_counter()
        findings: dict[str, Finding] = {}
        notes: list[str] = []

        # One JVM per process: open the JDBC connection here, before any thread
        # could race to start it (the pertussis agent uses the same driver).
        self.agent.client.connect()

        # Where exactly is the destination? Asked through Zetaris (the Open-Meteo geocoding
        # API registered as a REST table); its county drives the county-level wastewater checks.
        place = None
        emit({"stage": "location", "state": "start", "city": trip.to_city})
        try:
            place = geocode.resolve(self.agent.client, trip.to_city, trip.to_state)
        except Exception as e:  # noqa: BLE001  the page's own lookup still stands
            notes.append(f"location: Zetaris lookup failed ({str(e)[:120]}); using the page's county")
            emit({"stage": "location", "state": "failed", "error": str(e)[:160]})
        if place is not None:
            if place.county and place.county != trip.to_county:
                notes.append(f"location: county set to {place.county} from {place.table} (page had {trip.to_county})")
                trip = replace(trip, to_county=place.county)
            emit({"stage": "location", "state": "done", "place": f"{place.name}, {place.state}",
                  "county": place.county, "table": place.table, "seconds": round(place.seconds, 1)})
        elif not any(n.startswith("location:") for n in notes):
            notes.append(f"location: {trip.to_city} not found through Zetaris; using the page's county")
            emit({"stage": "location", "state": "failed", "error": "not found"})

        def done(f: Finding) -> None:
            findings[f.source] = f
            if f.status == "ok":
                emit({"stage": f.source, "state": "done", "level": f.level, "model": f.model, "seconds": round(f.seconds, 1)})
            else:
                notes.append(f"{f.source}: {f.error}")
                emit({"stage": f.source, "state": "failed", "error": f.error, "seconds": round(f.seconds, 1)})

        def task_wastewater() -> None:
            for key, source in (("sars-cov-2", "covid"), ("flu-a", "flu")):
                emit({"stage": source, "state": "start"})
                done(wastewater.run(self.agent, trip, key, progress=emit))

        def task_pertussis_guidance() -> None:
            emit({"stage": "pertussis", "state": "start"})
            p = pertussis.run(trip)
            done(p)
            emit({"stage": "guidance", "state": "start"})
            done(guidance.run(trip, pertussis_rising=p.status == "ok" and p.level in ("moderate", "high")))

        def task_weather() -> None:
            emit({"stage": "weather", "state": "start"})
            done(weather.run(trip, base_url=self.weather_url, timeout=TIMEOUTS["weather"]))

        # Wastewater and weather run in worker threads; pertussis and guidance run on
        # the calling thread. They open a second JDBC connection, and JPype cannot
        # unwind a JVM session begun from a worker at interpreter exit, which hangs
        # the CLI. The JVM itself was started above on this thread.
        pool_tasks = {"wastewater": task_wastewater, "weather": task_weather}
        with ThreadPoolExecutor(max_workers=len(pool_tasks)) as pool:
            futures = {name: pool.submit(fn) for name, fn in pool_tasks.items()}
            try:
                task_pertussis_guidance()
            except ProviderUnauthorized:
                raise
            except Exception as e:  # noqa: BLE001
                for source in SOURCES_OF["pertussis_guidance"]:
                    if source not in findings:
                        done(failed(source, f"{e.__class__.__name__}: {str(e)[:200]}"))
            for name, fut in futures.items():
                try:
                    fut.result(timeout=TIMEOUTS[name])
                except TimeoutError:
                    for source in SOURCES_OF[name]:
                        if source not in findings:
                            done(failed(source, f"timed out after {TIMEOUTS[name]:.0f} s"))
                except ProviderUnauthorized:
                    raise
                except Exception as e:  # noqa: BLE001  a bug in one task must not lose the other findings
                    for source in SOURCES_OF[name]:
                        if source not in findings:
                            done(failed(source, f"{e.__class__.__name__}: {str(e)[:200]}"))

        replans = self.replan(trip, findings, notes, emit)

        state, _ = self.agent.nightshift.readiness()
        if state == "unauthorized":
            raise ProviderUnauthorized("Nightshift rejected the token; check the token file")
        provider = self.agent.nightshift if state == "online" else None
        emit({"stage": "composer", "state": "start", "model": provider.model if provider else "template"})
        plan = compose(trip, findings, provider, elapsed=time.perf_counter() - t0, notes=notes, emit=emit)
        plan.elapsed_seconds = time.perf_counter() - t0
        plan.evaluation["replans"] = replans
        if place is not None:
            plan.trip["location"] = place.to_dict()
            plan.sources.insert(0, {"title": f"Open-Meteo geocoding API, via Zetaris table {place.table}",
                                    "url": "https://open-meteo.com/en/docs/geocoding-api"})
        ev = plan.evaluation
        emit({"stage": "composer", "state": "done", "model": plan.models["composer"], "level": plan.verdict.level,
              "seconds": round(plan.elapsed_seconds, 1), "evaluation": ev.get("final"), "rounds": len(ev.get("rounds", []))})
        return plan

    # -- the Evaluator's way back to the planner ------------------------------

    def rerun(self, req: "evaluator.ReplanRequest", trip: TripRequest, findings: dict[str, Finding]) -> Finding:
        src = req.source
        if src in PATHOGEN_OF:
            ask = replace(trip, to_county=None) if req.action == "state_level" else trip
            f = wastewater.run(self.agent, ask, PATHOGEN_OF[src])
            if req.action == "state_level" and f.status == "ok":
                f.caveats.insert(0, f"No recent samples for {trip.to_county}, so this is the state-wide reading, "
                                    "asked for again at the evaluator's request.")
            return f
        if src == "pertussis":
            return pertussis.run(trip)
        if src == "guidance":
            p = findings.get("pertussis")
            return guidance.run(trip, pertussis_rising=bool(p and p.status == "ok" and p.level in ("moderate", "high")))
        if src == "weather":
            return weather.run(trip, base_url=self.weather_url, timeout=TIMEOUTS["weather"])
        raise ValueError(f"no way to re-ask {src}")

    def replan(self, trip: TripRequest, findings: dict[str, Finding], notes: list[str], emit: Progress) -> list[dict[str, Any]]:
        """The Evaluator reviews the findings; the planner asks again where it says so. A new
        answer replaces the old only when it tells the reader more (see evaluator.usefulness)."""
        rounds: list[dict[str, Any]] = []
        for rnd in range(1, MAX_REPLANS + 1):
            requests = evaluator.review_findings(trip, findings)
            emit({"stage": "evaluator", "state": "findings", "round": rnd, "requests": [r.to_dict() for r in requests]})
            if not requests:
                break
            results = []
            for req in requests:
                old = findings[req.source]
                emit({"stage": req.source, "state": "start", "retry": True, "action": req.action})
                try:
                    new = self.rerun(req, trip, findings)
                except ProviderUnauthorized:
                    raise
                except Exception as e:  # noqa: BLE001  a failed re-ask keeps the first answer
                    new = failed(req.source, f"{e.__class__.__name__}: {str(e)[:200]}")
                keep_new = evaluator.usefulness(new) > evaluator.usefulness(old)
                if keep_new:
                    findings[req.source] = new
                    notes.append(f"{req.source}: asked again ({req.action}) at the evaluator's request; the new answer is used")
                else:
                    notes.append(f"{req.source}: asked again ({req.action}) at the evaluator's request; the first answer is kept")
                kept = new if keep_new else old
                emit({"stage": req.source, "state": "done" if kept.status == "ok" else "failed", "retry": True,
                      "action": req.action, "kept": "new" if keep_new else "old", "level": kept.level,
                      "model": kept.model, "error": kept.error, "seconds": round(new.seconds, 1)})
                results.append({**req.to_dict(), "kept": "new" if keep_new else "old",
                                "before": {"status": old.status, "level": old.level, "headline": old.headline},
                                "after": {"status": new.status, "level": new.level, "headline": new.headline}})
            rounds.append({"round": rnd, "requests": results})
        return rounds

    def close(self) -> None:
        self.agent.close()
