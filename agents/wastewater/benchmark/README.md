# Agent benchmark

Run from `wastewater/`:

```bash
python -m wastewater_agent benchmark
```

Scores the agent against `questions.json` (11 questions, each with the plan it
must produce) in three layers and writes `results-<timestamp>.json` here.

| Layer | Measures | Needs |
|---|---|---|
| `plan` | planner accuracy: intent, state and window exactly as expected, per routed model; offline fallbacks; latency | Nightshift only |
| `answer` | writer fidelity: first-attempt pass of the figure check, retries, template fallbacks, coverage, latency, plus a `meterless/judge` fidelity and clarity score with its receipt | Zetaris and Nightshift |
| `memory` | cross-session recall: a second, fresh agent asks the same questions and must use the memory the first run stored; superseded records must not outrank live ones | Zetaris and Nightshift |

Options: `--layers plan,answer,memory`, `--repeats N` (plan layer; repeat to
see route-to-route variance), `--no-judge`, `--questions FILE`, `--out FILE`.

The answer and memory layers use their own store, `../.hmem_bench/`, wiped at
the start of each run, so the agent's real `.hmem/` is untouched. The judge
sees only the model's own sentences (the appended "Earlier finding on record"
sentence is stripped), so recalled numbers are never scored against the
current fact sheet.

Window specs in `questions.json`: `last_week`, `last_N_days`, `this_month`,
`last_month`, `yesterday`, `month:YYYY-MM`, an explicit `{start, end}`, or
`any` when any valid past window is acceptable.

Layers 2 and 3 benchmark the agent's control logic (figure check, fallbacks,
memory). To benchmark the model routes themselves, submit the writer prompt
and a fact sheet as a Nightshift `best_of_n` job with `judge_mode: accuracy`;
that needs fleet lanes and produces a panel verdict and report.
