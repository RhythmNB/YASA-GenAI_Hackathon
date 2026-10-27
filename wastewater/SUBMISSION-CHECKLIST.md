# Submission checklist (rules section 3.3, GitHub repository)

Tick each row before the deadline. "Where" is the file judges will open.

## Required

| Item | Where | State |
|---|---|---|
| Repository is public | GitHub settings | [ ] make public before submitting |
| README: setup from a clean clone | `README.md` (root), section "Setup" | [x] written; [ ] test it on a clean clone |
| README: usage with sample inputs | `README.md` section "Usage" | [x] |
| README: dependencies incl. Zetaris and Nightshift | `README.md` section "Dependencies" | [x] |
| Colab links | `README.md` top table | [x] states "not used" |

## Recommended

| Item | Where | State |
|---|---|---|
| Three sample inputs and outputs | `samples/README.md` | [ ] fill from real runs (see below) |
| Logs or traces, including which model handled each request | `samples/traces/*.json`, `benchmark/results-*.json`, receipts in every answer | [ ] copy the three trace files; [ ] keep at least one results file |
| Test or conformance check for the Meterless engine | `samples/conformance.md` (captured `status`), `benchmark/README.md` | [x] captured 2026-10-27 |
| `.env.example` with placeholders only | `.env.example` | [x] |
| `SAMPLE_MODE=true` fallback | page: `?demo=1` works with no services. CLI: not implemented | [ ] decide: implement in the agent, or document the page-only fallback as is |

## Secrets and ignore rules (check before the first push)

- [ ] `.env` is ignored (yes, in `wastewater/.gitignore`) and no `.env` is tracked: `git ls-files | findstr /i "\.env"` must print only `.env.example`
- [ ] no token or password in any committed file: `git grep -n -i "password\|token\|api_key" -- . ":!*.md"` and read every hit
- [ ] `data/` is ignored so the CSVs (hundreds of MB) never get committed
- [ ] `.hmem/` and `.hmem_bench/` are ignored (memory stores carry local paths and answers)
- [ ] `wastewater/.gitignore` ignores `docs/`, `benchmark/` and `benchmark.py` (deliberate, decided 2026-10-27). If that stays, before pushing either drop the `benchmark` command and the references to `benchmark/` and `docs/` from `README.md` and `samples/conformance.md`, or unignore them then
- [ ] `.claude/` at the repo root is untracked: either ignore it or commit only `launch.json`

## Before the deadline

- [ ] `git status` is clean on the branch you submit and the branch is pushed
- [ ] the README links (video, slides) resolve
- [ ] a teammate who has not run the project follows `README.md` from a clean clone and gets `python -m wastewater_agent status` green
