# Pipeline Incident Copilot

An LLM copilot that diagnoses failed dbt pipeline runs, plus the harness to prove how well it works.

When `dbt build` fails, the copilot reads the run artifacts, profiles the source data, looks at recent code changes, and returns a structured diagnosis: the root-cause category, the node and column at fault, an explanation that cites the evidence, and a concrete fix. Every number in this README comes from a labelled set of 20 reproducible incidents, and a CI gate fails the build if accuracy regresses.

It runs entirely on free tiers: DuckDB locally, and Groq, Google AI Studio, OpenRouter or a local Ollama model for the LLM.

## Why

On-call data engineers spend most of an incident working out *where* the problem is: did the upstream feed change, did someone's commit break a model, or is this a downstream symptom of something earlier? The answer is usually sitting in the logs, the data profile and the git diff, but spread across all three. This project asks how far an LLM can get by reading them together, and measures it instead of demoing it.

## How it works

```
 scenarios.yaml ──> fault injector ──> dbt build (DuckDB) ──> evidence bundle ──> agent ──> diagnosis
   (labelled)       data or code         real failures         ~1k tokens          LLM      scored vs label
```

1. **Fault injection.** Each scenario copies the pipeline and breaks it in a known way, either a bad data delivery (a unit change, nulls, a renamed column, numbers arriving as strings) or a bad commit (a typo, a removed filter, a wrong transformation). Some scenarios also include harmless code edits, because real incidents never come with a clean git history.
2. **Evidence.** A real `dbt build` runs and fails. `run_results.json` and `manifest.json` are distilled into a compact bundle: failing nodes and messages, test arguments, sample failing rows, downstream skips, lineage, a source profile (types, ranges, nulls, samples) and the code diff since the last good run.
3. **Diagnosis.** The agent sends the bundle to an LLM with a fixed set of categories and gets back JSON. A rule-based baseline (regexes and if-statements, no LLM) does the same job as the floor to beat.
4. **Evaluation.** Each diagnosis is scored on category, root-cause node and column. Reports include accuracy by category, latency and token use.

The pipeline under test is the Spotify reference implementation from [dbt_schema_aware_pipeline](https://github.com/rahil1303/dbt_schema_aware_pipeline), whose data quality contracts (`in_range`, `completeness_above`) are what catch most of the bad data.

## Results

| Approach | Fully correct | Category | Notes |
|---|---|---|---|
| Rule-based baseline | 50% | 75% | Reads error messages well; blames any code change, harmless or not |
| Groq `openai/gpt-oss-120b` | _run `copilot eval --provider groq`_ | | |
| Gemini `gemini-2.5-flash` | _run `copilot eval --provider gemini`_ | | |
| Ollama `llama3.1:8b` (local) | _run `copilot eval --provider ollama`_ | | |

*Fully correct* means category, root-cause node and column all match the label. Full per-scenario reports are written to `reports/`.

## Incident categories

| Category | Example scenario |
|---|---|
| `out_of_range` | Upstream export switched `energy` from a 0-1 score to a percentage |
| `null_values` | Feature extraction timed out for 10% of tracks |
| `schema_drift` | Producer renamed `tempo` to `bpm` |
| `type_mismatch` | `tempo` arrives as `'120.5 bpm'` |
| `sql_logic_error` | A commit wrapped `loudness` in `abs()` |

The hard cases are the pairs that look identical in the test output but differ in cause. `oor_energy_percent` (bad data) and `sql_energy_rescaled_in_staging` (bad commit) fail the same test on the same column; only the source profile and the diff tell them apart.

## Quickstart

```bash
git clone https://github.com/rahil1303/pipeline-incident-copilot
cd pipeline-incident-copilot
pip install -e ".[dev]"

cp .env.example .env        # add a free GROQ_API_KEY (console.groq.com, no card)

copilot eval --provider baseline --provider groq
```

The evidence bundles are committed, so evals need no dbt or database. To regenerate them from real dbt runs:

```bash
pip install -e ".[dbt]"
(cd dbt_project && dbt deps --profiles-dir .)
copilot collect             # ~5 s per scenario
```

Diagnose a single incident:

```bash
copilot diagnose --bundle evidence/sql_removed_tempo_filter.json --provider groq
```

Providers can be chained for resilience (free tiers rate-limit and retire models): `--provider groq,gemini,ollama` tries each in turn. Pin a model with `groq:openai/gpt-oss-20b`.

### On your own dbt project

The evidence builder works on any dbt `target/` directory:

```bash
dbt build                                   # in your project; let it fail
git diff HEAD~1 -- models > /tmp/changes.diff
copilot diagnose --target path/to/target --diff-file /tmp/changes.diff --provider groq
```

Add `--duckdb warehouse.duckdb --source-table <table>` to include a source profile when using DuckDB.

## CI

- **`ci.yml`** runs lint and tests, regenerates all evidence from real dbt builds and runs the baseline eval on every push.
- **`llm-eval.yml`** re-scores the LLM whenever the agent, prompt or scenarios change, and fails the check if the fully-correct rate drops below `MIN_ACCURACY`. Add `GROQ_API_KEY` under repo Settings > Secrets and variables > Actions to enable it.

## Project layout

```
src/incident_copilot/
  faults.py        fault injectors (data and code)
  dbt_runner.py    copy pipeline, inject, dbt build, collect
  evidence.py      dbt artifacts -> compact evidence bundle
  prompts.py       system prompt and categories
  agent.py         LLM call + JSON parsing
  baseline.py      rule-based baseline
  evaluate.py      scoring and reports
  llm/providers.py Groq / Gemini / OpenRouter / Ollama, retries, fallback chain
  cli.py           copilot collect | diagnose | eval
dbt_project/       Spotify pipeline on DuckDB (uses dbt_schema_aware_pipeline)
scenarios/         20 labelled incidents
evidence/          committed evidence bundles
reports/           eval reports
```

The seed in `dbt_project/seeds/` is a synthetic 600-row sample with the same columns and ranges as the [Kaggle Spotify Tracks dataset](https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset), which cannot be redistributed. Regenerate it with `python scripts/make_seed.py`.

## Roadmap

- Energy and cost per diagnosis across model sizes (local models measured with CodeCarbon), to find where a smaller model is good enough
- LLM-as-judge scoring for the quality of suggested fixes
- Multi-incident scenarios and noisier logs
- A hosted demo on Hugging Face Spaces

## License

MIT
