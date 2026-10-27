# Visit Planner: data layer and two agents (handover from Sandeep)

These are two agents the planner can call. Both return the same shape:

```python
{"agent": ..., "briefing": str, "facts": dict, "sources": [{"id", "title", "url", ...}], "caveats": [...], ...}
```

| Agent | What it does | Uses an LLM? |
|---|---|---|
| `agents/pertussis_agent.py` → `pertussis_activity(["CA", "AZ"])` | Reads state whooping cough counts from Zetaris. Compares this year with last year and with the national rate, and flags small numbers and missing data. Writes a paragraph. | Yes. The model only polishes a safe template. Every number is checked, a second "reviewer" call checks the meaning, there are up to 3 tries, and the template is the fallback. |
| `agents/guidance_agent.py` → `guidance_for_visit("newborn", priority=["pertussis"])` | Picks the CDC advice that fits who is being visited (`newborn` or `older_adult`; `pregnant=True` adds pregnancy advice) and quotes it word for word with sources and dates. Rows marked CHECK get a "check with a healthcare provider" caveat. | No. It uses rules only, so the medical advice is never rewritten. |

## Quick start without Zetaris (works straight away)

```bash
cd agents
python pertussis_agent.py AZ CA --no-llm --csv ../data/pertussis_state_2026w41.csv
python guidance_agent.py newborn --priority pertussis --csv ../data/cdc_guidance_2026-10-26.csv
```

The CSVs are snapshots of the Zetaris tables, with data up to week 41 of 2026. Use them to build the planner while your own Zetaris is being set up.

## Planner sketch

```python
from pertussis_agent import pertussis_activity
from guidance_agent import guidance_for_visit

act = pertussis_activity(["CA", "AZ"])          # start and end states, from the Location agent
rising = any(s.get("trend", "").startswith("higher") for s in act["facts"]["states"])
guide = guidance_for_visit("newborn", priority=["pertussis"] if rising else [])
# The composer writes the intro and summary; quote guide["briefing"] as it is; merge sources and caveats.
```

## Full setup with Zetaris (about 20 minutes)

1. **Zetaris:** use the Docker bundle from Zetaris Cloud (docker login, `docker compose pull`, `docker compose up -d`, `./verify.sh`), then sign in at http://localhost:3000.
2. **Repo:** clone `zetaris/getting-started` **into this folder**, so you have `visit-planner-handoff/getting-started/`. The agents look for `../getting-started/scripts`.
3. **Settings:** copy `getting-started/.env.example` to `getting-started/.env.local`, then fill it in using `env.example` here as a guide. You need an API key (UI → Management → API Tokens → +) and the org ID (Management → Organisation; it's `1` on a fresh install).
4. **Load the reference files** (run in the `zetaris-platform` folder):
   ```bash
   docker compose exec -u 0 driver mkdir -p /home/zetaris/customer-data/shared/census /home/zetaris/customer-data/shared/guidance
   docker compose cp <path>/data/census_state_pop_2025.csv driver:/home/zetaris/customer-data/shared/census/
   docker compose cp <path>/data/cdc_guidance_2026-10-26.csv driver:/home/zetaris/customer-data/shared/guidance/
   docker compose exec -u 0 driver chown -R zetaris:zetaris /home/zetaris/customer-data/shared
   ```
   Without the `chown` step, Zetaris gives a "Permission denied" error.
5. **SQL:** run `sql/setup.sql` one statement at a time in the SQL Workspace (Workbench → SQL Workspace → New Query, then Cmd+Return).
6. **Test:** `python agents/pertussis_agent.py AZ CA --no-llm` should print Arizona at 1019 cases, 13.37 per 100k.

## Meterless Nightshift: lessons learned

- **Local models failed:** the on-device models (Llama, Qwen and Gemma 3B) gave `model_load_failed` through the API on Sandeep's M2 Max, even though they worked inside the app. NVIDIA through Nightshift works. Add a key from build.nvidia.com in Nightshift → Setup → Providers.
- **Model:** `nvidia/nemotron-3.5-lightning-30b-a3b`.
- **Speed:** the free tier is slow, about 1 to 2 minutes per call, and sometimes times out. The agent waits up to 5 minutes and then falls back to the template. `--no-review` halves the number of calls. For the demo, record the run in advance.
- **Fresh Terminal:** run the agents from a fresh Terminal window. Old `source .env.local` exports override the file.
- **Every session:** start Docker (`docker compose up -d`) and keep the Nightshift window open.

## Data caveats to keep in the briefing

- Pertussis counts are state-level only (NYC is the exception), provisional and often revised.
- Missouri, Delaware and DC have no complete 2026 count. That's a reporting gap, not zero.
- **CDC guidance:**
  - Infant RSV: the 5 Jan 2026 schedule change made infant RSV immunization no longer routine, but CDC's RSV page predates it. The agent adds a "check with a provider" caveat.
  - COVID: the rows cover the 2025–26 vaccine. Check for a 2026–27 update.
