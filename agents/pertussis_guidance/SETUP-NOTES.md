# Setup notes for this machine (Windows, 2026-10-27)

What was done to make `HANDOFF.md` work here, and where it differs from the
handoff's Mac-oriented steps.

## Layout

- This folder is a copy of `agents/pertussis_guidance.zip` placed inside the
  hackathon repo next to `wastewater/`.
- `getting-started/` here is a directory junction to the existing clone at
  `F:\Hackathon\getting-started` (the agents look for `../getting-started/scripts`).
  It is git-ignored by the `.gitignore` in this folder, so the clone is not
  vendored into the repo.

## Settings

`F:\Hackathon\getting-started\.env.local` (backed up as `.env.local.bak-20261027`)
gained:

- `ZETARIS_ORG_ID=1`
- the `METERLESS_*` keys from `env.example`; `METERLESS_API_KEY` is the
  Nightshift runtime's proxy token (read from
  `%LOCALAPPDATA%\ai.meterless.runtime\proxy-token`)
- `JAVA_HOME=F:\jdk-23.0.2`, so the JDBC channel finds the JDK without an
  exported variable

`ZETARIS_API_KEY` is still empty. It is only needed for the REST channel
(`--channel rest`, the agents' default). Create one in the Zetaris UI under
Management → API Tokens and paste it in, or keep using `--channel jdbc`.

## Zetaris

- Reference CSVs were copied into the driver container
  (`zetaris-driver-1:/home/zetaris/customer-data/shared/{census,guidance}/`)
  with the `chown` step from the handoff. In Git Bash use `MSYS_NO_PATHCONV=1`
  and Windows-style source paths, or `docker cp` rewrites the paths.
- `sql/setup.sql` ran through JDBC with `sql/run_setup_jdbc.py` rather than
  the SQL Workspace. The getting-started `run_sql.py` cannot run statement 2
  over JDBC: the driver reads the `?` in the CDC URL as a bind parameter
  ("Parameter #1 is unset"). The runner uses a plain JDBC `Statement`, which
  passes the text through, and skips statements that already exist.
- Checks passed: `pertussis_state_rates` has 52 rows with Arizona first at
  13.37 per 100k; `cdc_guidance` has 12 rows.

## getting-started patch

`scripts/zetaris_sql.py` in the clone: `find_java_home()` only accepted
`bin/java`; it now also accepts `bin/java.exe`. One line, uncommitted in that
clone. Without it every JDBC call on Windows fails with "No JDK found".

## Nightshift

The handoff's model (`nvidia/nemotron-3.5-lightning-30b-a3b`) returned
`empty_response` (HTTP 502) on the first try, and `nvidia/nemotron-3-ultra-550b-a55b`
returned its hidden reasoning as content, which the number check rejected
three times. Both are the same cause: Nemotron routes reason before answering
unless told not to. `agents/pertussis_agent.py` now sends
`"chat_template_kwargs": {"enable_thinking": false}` in the Meterless request
(one added line next to `max_tokens`). With it, both models write the
paragraph on attempt 1, in well under a minute here, so `METERLESS_MODEL` in
`.env.local` keeps the handoff's lightning default.

## Verified commands (run from this folder)

```bash
# offline, CSV snapshots
python agents/pertussis_agent.py AZ CA --no-llm --csv data/pertussis_state_2026w41.csv
python agents/guidance_agent.py newborn --priority pertussis --csv data/cdc_guidance_2026-10-26.csv

# against Zetaris over JDBC
python agents/pertussis_agent.py AZ CA --no-llm --channel jdbc
python agents/guidance_agent.py newborn --priority pertussis --channel jdbc

# with the Nightshift model (slow; --no-review halves the calls)
python agents/pertussis_agent.py AZ CA --channel jdbc --no-review
```
