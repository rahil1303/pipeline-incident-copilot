"""Score diagnoses against scenario labels and write a report."""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .agent import Agent
from .schemas import CATEGORIES, Diagnosis, normalise_column, normalise_node


def score(d: Diagnosis, label: dict) -> dict[str, Any]:
    cat = d.category == label["category"]
    node = normalise_node(d.root_cause_node) == normalise_node(label["root_cause_node"])
    want_col = normalise_column(label.get("column"))
    col = None if want_col is None else normalise_column(d.column) == want_col
    return {
        "category_correct": cat,
        "node_correct": node,
        "column_correct": col,
        "fully_correct": cat and node and col is not False,
    }


def load_bundles(evidence_dir: Path, only: list[str] | None = None) -> list[dict]:
    bundles = [json.loads(p.read_text()) for p in sorted(evidence_dir.glob("*.json"))]
    if only:
        bundles = [b for b in bundles if b["scenario_id"] in only]
    if not bundles:
        raise FileNotFoundError(f"no evidence bundles in {evidence_dir}; run `copilot collect` first")
    return bundles


def run_eval(provider: str, evidence_dir: Path, only: list[str] | None = None,
             progress: bool = True) -> dict[str, Any]:
    agent = Agent(provider)
    rows = []
    for b in load_bundles(evidence_dir, only):
        d = agent.diagnose(b["evidence"])
        s = score(d, b["label"])
        rows.append({"scenario_id": b["scenario_id"], "label": b["label"],
                     "diagnosis": d.to_dict(), **s})
        if progress:
            mark = "OK " if s["fully_correct"] else ("~  " if s["category_correct"] else "X  ")
            print(f"  {mark}{b['scenario_id']:34} -> {d.category or 'ERROR'} @ "
                  f"{d.root_cause_node or '-'} [{d.column}]  {d.latency_s:.2f}s", flush=True)
            if not d.parse_ok:
                print(f"       reason: {' '.join(d.raw.split())[:300]}", flush=True)
    return summarise(provider, rows)


def _rate(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarise(provider: str, rows: list[dict]) -> dict[str, Any]:
    per_cat: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        per_cat[r["label"]["category"]].append(r["fully_correct"])
    lat = [r["diagnosis"]["latency_s"] for r in rows]
    ptok = [r["diagnosis"]["prompt_tokens"] for r in rows if r["diagnosis"]["prompt_tokens"]]
    ctok = [r["diagnosis"]["completion_tokens"] for r in rows if r["diagnosis"]["completion_tokens"]]
    models = sorted({r["diagnosis"]["model"] for r in rows if r["diagnosis"]["model"]})
    return {
        "provider": provider,
        "models": models,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n": len(rows),
        "metrics": {
            "fully_correct": _rate([r["fully_correct"] for r in rows]),
            "category_accuracy": _rate([r["category_correct"] for r in rows]),
            "node_accuracy": _rate([r["node_correct"] for r in rows]),
            "column_accuracy": _rate([r["column_correct"] for r in rows]),
            "parse_rate": _rate([r["diagnosis"]["parse_ok"] for r in rows]),
            "latency_mean_s": round(statistics.mean(lat), 3) if lat else None,
            "latency_max_s": round(max(lat), 3) if lat else None,
            "prompt_tokens_total": sum(ptok) or None,
            "completion_tokens_total": sum(ctok) or None,
        },
        "per_category_fully_correct": {c: _rate(per_cat[c]) for c in CATEGORIES if per_cat[c]},
        "rows": rows,
    }


def to_markdown(report: dict) -> str:
    m = report["metrics"]
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    lines = [
        f"# Eval report: `{report['provider']}`",
        "",
        f"{report['n']} scenarios, models: {', '.join(report['models']) or '-'}, run {report['timestamp']}",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Fully correct (category + node + column) | **{pct(m['fully_correct'])}** |",
        f"| Category accuracy | {pct(m['category_accuracy'])} |",
        f"| Root-cause node accuracy | {pct(m['node_accuracy'])} |",
        f"| Column accuracy | {pct(m['column_accuracy'])} |",
        f"| Valid JSON replies | {pct(m['parse_rate'])} |",
        f"| Mean latency | {m['latency_mean_s']} s |",
        f"| Tokens (prompt / completion) | {m['prompt_tokens_total']} / {m['completion_tokens_total']} |",
        "", "## By category", "", "| Category | Fully correct |", "|---|---|",
    ]
    lines += [f"| {c} | {pct(v)} |" for c, v in report["per_category_fully_correct"].items()]
    lines += ["", "## Scenarios", "", "| Scenario | Expected | Diagnosed | OK |", "|---|---|---|---|"]
    for r in report["rows"]:
        lab, d = r["label"], r["diagnosis"]
        exp = f"{lab['category']} @ {lab['root_cause_node']} [{lab['column']}]"
        got = f"{d['category'] or 'ERROR'} @ {d['root_cause_node'] or '-'} [{d['column']}]"
        lines.append(f"| {r['scenario_id']} | {exp} | {got} | {'yes' if r['fully_correct'] else 'no'} |")
    return "\n".join(lines) + "\n"


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = report["provider"].replace(",", "+").replace(":", "_").replace("/", "_")
    j, md = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    j.write_text(json.dumps(report, indent=2, default=str))
    md.write_text(to_markdown(report))
    return j, md
