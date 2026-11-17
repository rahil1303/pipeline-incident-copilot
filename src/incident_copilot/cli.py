"""Command line: `copilot collect | diagnose | eval`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader so API keys never need to be exported by hand."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_collect(a: argparse.Namespace) -> int:
    from .dbt_runner import run_scenario, write_bundle
    from .schemas import load_scenarios

    scenarios = load_scenarios(a.scenarios)
    if a.only:
        scenarios = [s for s in scenarios if s.id in a.only]
    print(f"Running {len(scenarios)} scenarios against {a.project} ...")
    for s in scenarios:
        b = run_scenario(Path(a.project), s)
        write_bundle(b, Path(a.out))
        failed = [f["node"] for f in b["evidence"]["failures"]]
        print(f"  {s.id:34} {b['dbt_build_seconds']:5.1f}s  failing: {', '.join(failed)[:70]}")
    print(f"Evidence written to {a.out}/")
    return 0


def cmd_diagnose(a: argparse.Namespace) -> int:
    from .agent import Agent
    from .evidence import build_evidence

    if a.bundle:
        data = json.loads(Path(a.bundle).read_text())
        evidence = data.get("evidence", data)
    else:
        diff = Path(a.diff_file).read_text() if a.diff_file else None
        evidence = build_evidence(
            Path(a.target),
            duckdb_path=Path(a.duckdb) if a.duckdb else None,
            source_table=a.source_table,
            diff_text=diff,
        )
    d = Agent(a.provider).diagnose(evidence)
    if a.json:
        print(json.dumps(d.to_dict(), indent=2))
    else:
        print(f"Category:    {d.category}\nRoot cause:  {d.root_cause_node}  (column: {d.column})")
        if d.confidence is not None:
            print(f"Confidence:  {d.confidence:.2f}")
        if d.explanation:
            print(f"\nWhy: {d.explanation}")
        if d.suggested_fix:
            print(f"\nFix: {d.suggested_fix}")
        print(f"\n[{d.provider}:{d.model} in {d.latency_s:.2f}s]")
        if not d.parse_ok:
            print(f"\nCould not parse a valid diagnosis. Raw reply:\n{d.raw[:1000]}")
    return 0 if d.parse_ok else 1


def cmd_eval(a: argparse.Namespace) -> int:
    from .evaluate import run_eval, write_report

    worst = 1.0
    for provider in a.provider:
        print(f"\n== {provider}")
        report = run_eval(provider, Path(a.evidence), a.only)
        _, md = write_report(report, Path(a.out))
        m = report["metrics"]
        print(f"   fully correct {m['fully_correct']:.0%} | category {m['category_accuracy']:.0%} | "
              f"mean latency {m['latency_mean_s']}s  ->  {md}")
        worst = min(worst, m["fully_correct"] or 0.0)
    if a.min_accuracy is not None and worst < a.min_accuracy:
        print(f"\nEval gate FAILED: {worst:.0%} < required {a.min_accuracy:.0%}")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="copilot", description="AI incident copilot for dbt pipelines")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="break the pipeline per scenario and save evidence bundles")
    c.add_argument("--scenarios", default="scenarios/scenarios.yaml")
    c.add_argument("--project", default="dbt_project")
    c.add_argument("--out", default="evidence")
    c.add_argument("--only", nargs="*")
    c.set_defaults(func=cmd_collect)

    d = sub.add_parser("diagnose", help="diagnose one failed run")
    src = d.add_mutually_exclusive_group(required=True)
    src.add_argument("--bundle", help="evidence bundle JSON (from `collect`)")
    src.add_argument("--target", help="a dbt target/ dir from any real project")
    d.add_argument("--duckdb", help="DuckDB file, for source profiling (optional)")
    d.add_argument("--source-table", default="raw_tracks")
    d.add_argument("--diff-file", help="output of `git diff` since last good run (optional)")
    d.add_argument("--provider", default="groq", help="groq | gemini | ollama | openrouter | baseline, "
                                                     "optional ':model', comma list = fallback")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_diagnose)

    e = sub.add_parser("eval", help="score providers on all evidence bundles")
    e.add_argument("--provider", action="append", default=None,
                   help="repeat to compare, e.g. --provider baseline --provider groq")
    e.add_argument("--evidence", default="evidence")
    e.add_argument("--out", default="reports")
    e.add_argument("--only", nargs="*")
    e.add_argument("--min-accuracy", type=float, help="exit 2 if fully-correct rate is below this")
    e.set_defaults(func=cmd_eval)

    a = p.parse_args(argv)
    if a.cmd == "eval" and not a.provider:
        a.provider = ["baseline"]
    from .llm import ProviderError

    try:
        return a.func(a)
    except (ProviderError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
