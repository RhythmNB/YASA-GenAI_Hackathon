# Meterless engine check

Captured 2026-10-27 with `python -m wastewater_agent status` from `wastewater/`.
It lists the routes the Nightshift runtime exposes to this app and their
availability, and confirms both Zetaris tables answer a `MAX(sample_collect_date)`
query. Re-capture it on the submission day and replace the block below.

```
zetaris:
  ok  jdbc:zetaris:lightning@localhost:10000
    SARS-CoV-2   wastewater.sars_cov_2      latest sample 2026-10-13
    influenza A  wastewater.influenza_a     latest sample 2026-10-20
nightshift:
  online  http://127.0.0.1:8088/v1  token from file <LOCALAPPDATA>\ai.meterless.runtime\proxy-token
    meterless/auto       availability=ready
    meterless/fast       availability=ready
    meterless/deep       availability=ready
    meterless/cheap      availability=ready
    meterless/local      availability=ready
    meterless/fusion     availability=ready
    meterless/text       availability=ready
    meterless/code       availability=ready
    meterless/vision     availability=cloud
    meterless/video      availability=cloud
    meterless/embed      availability=cloud
    meterless/judge      availability=ready
    routed owners: google (13), local-runtime (51), nvidia (6)
memory:
  short_term 0
  working    29
  long_term  0
  archived   0
  dir        <repo>\wastewater\.hmem
```

## Functional check

The benchmark's plan layer sends every question in `benchmark/questions.json`
through Nightshift and records which model planned it:

```bash
python -m wastewater_agent benchmark --layers plan
```

Last run (2026-10-26, `benchmark/results-20261026T092520Z.json`):

```
plan:    exact 14/14  intent 14  state 14  window 14  pathogen 14  offline 1  median 4.58s
         nvidia/nemotron-3-ultra-550b-a55b: 13/13
         offline: 1/1
```

The one offline plan is the conversational question the rule-based planner is
expected to handle. A route change made since (routes tried in order, see
`NIGHTSHIFT_MODELS` in `.env.example`) does not change this layer's scoring.
