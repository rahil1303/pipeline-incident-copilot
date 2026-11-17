"""Turn the artifacts of a dbt run into a compact evidence bundle for diagnosis.

Works on any dbt project's ``target/`` directory, not just the demo pipeline.
Optional extras: a DuckDB file (for source profiling and failing-row samples)
and a baseline copy of the models (for a code diff, standing in for git).

The bundle is deliberately small (a few thousand tokens) so it fits the
per-minute token limits of free LLM tiers.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

MAX_MSG = 500
MAX_SQL = 1600
MAX_DIFF = 2500


def _trunc(s: str | None, n: int) -> str:
    if not s:
        return ""
    if n <= MAX_MSG:
        s = " ".join(s.split())
    else:  # keep line breaks (readable SQL), squeeze runs of spaces
        s = "\n".join(" ".join(line.split()) for line in s.strip().splitlines() if line.strip())
    return s if len(s) <= n else s[: n - 15] + " ...[truncated]"


def _short(unique_id: str) -> str:
    return unique_id.split(".")[-1] if unique_id.count(".") >= 2 else unique_id


# --------------------------------------------------------------------------- dbt artifacts

def load_artifacts(target_dir: Path) -> tuple[dict, dict]:
    run_results = json.loads((target_dir / "run_results.json").read_text())
    manifest_path = target_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"nodes": {}}
    return run_results, manifest


def lineage(manifest: dict) -> dict[str, list[str]]:
    """Model/seed -> direct parents, as bare names."""
    out = {}
    for uid, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") in {"model", "seed", "snapshot"}:
            parents = node.get("depends_on", {}).get("nodes", [])
            out[_short(uid)] = sorted(_short(p) for p in parents)
    return out


def summarise_results(run_results: dict, manifest: dict) -> tuple[dict, list[dict], dict]:
    summary: dict[str, int] = {}
    failures: list[dict] = []
    skipped: dict[str, Any] = {"models": [], "tests": 0}
    nodes = manifest.get("nodes", {})

    for r in run_results.get("results", []):
        status = r.get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
        uid = r.get("unique_id", "")
        if status == "skipped":
            if uid.startswith("test."):
                skipped["tests"] += 1
            else:
                skipped["models"].append(_short(uid))
            continue
        if status not in {"fail", "error", "warn", "runtime error"}:
            continue

        node = nodes.get(uid, {})
        item: dict[str, Any] = {
            "node": node.get("name") or _short(uid),
            "resource_type": node.get("resource_type", uid.split(".")[0]),
            "status": status,
            "message": _trunc(r.get("message"), MAX_MSG),
        }
        if item["resource_type"] == "test":
            meta = node.get("test_metadata") or {}
            item["test"] = meta.get("name") or _short(uid)
            item["column"] = node.get("column_name") or meta.get("kwargs", {}).get("column_name")
            attached = node.get("attached_node") or next(
                (p for p in node.get("depends_on", {}).get("nodes", [])), None)
            item["tested_model"] = _short(attached) if attached else None
            if r.get("failures") is not None:
                item["failing_rows"] = r["failures"]
            # Keep the test's arguments: they show what the contract expects.
            kwargs = {k: v for k, v in (meta.get("kwargs") or {}).items()
                      if k not in {"model", "column_name"}}
            if kwargs:
                item["test_args"] = kwargs
        compiled = r.get("compiled_code") or node.get("compiled_code")
        if compiled:
            item["compiled_sql"] = _trunc(compiled, MAX_SQL)
            item["_full_sql"] = compiled
        failures.append(item)

    return summary, failures, skipped


# --------------------------------------------------------------------------- code diff

def code_diff(baseline_models: Path, current_models: Path) -> str:
    """Unified diff of model files, like `git diff` since the last good run."""
    chunks: list[str] = []
    files = {p.relative_to(baseline_models) for p in baseline_models.rglob("*") if p.is_file()}
    files |= {p.relative_to(current_models) for p in current_models.rglob("*") if p.is_file()}
    for rel in sorted(files):
        a, b = baseline_models / rel, current_models / rel
        a_lines = a.read_text().splitlines(keepends=True) if a.exists() else []
        b_lines = b.read_text().splitlines(keepends=True) if b.exists() else []
        if a_lines != b_lines:
            chunks.extend(difflib.unified_diff(a_lines, b_lines, f"a/models/{rel}",
                                               f"b/models/{rel}", n=1))
    diff = "".join(chunks)
    return diff if len(diff) <= MAX_DIFF else diff[:MAX_DIFF] + "\n...[diff truncated]"


# --------------------------------------------------------------------------- warehouse

def _connect(duckdb_path: Path):
    import duckdb  # imported lazily: only needed when profiling

    return duckdb.connect(str(duckdb_path), read_only=True)


def _col_line(c: dict) -> str:
    """One compact line per column, e.g. 'tempo DOUBLE nulls=0 range=[60.2, 199.8]'."""
    line = f"{c['name']} {c['type']} nulls={c['nulls']}"
    if "min" in c:
        line += f" range=[{c['min']}, {c['max']}]"
    if c.get("samples"):
        line += " samples=" + json.dumps(c["samples"])
    return line


def profile_table(duckdb_path: Path, table: str) -> dict | None:
    """Column names, types, null counts, ranges and a few sample values."""
    con = _connect(duckdb_path)
    try:
        exists = con.execute(
            "select count(*) from information_schema.tables where table_name = ?", [table]
        ).fetchone()[0]
        if not exists:
            return None
        cols = con.execute(f'describe "{table}"').fetchall()
        n = con.execute(f'select count(*) from "{table}"').fetchone()[0]
        out_cols = []
        for name, ctype, *_ in cols:
            q = f'"{name}"'
            nulls = con.execute(f'select count(*) - count({q}) from "{table}"').fetchone()[0]
            col: dict[str, Any] = {"name": name, "type": ctype, "nulls": nulls}
            numeric = any(t in ctype.upper() for t in
                          ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC"))
            if numeric:
                lo, hi = con.execute(f'select min({q}), max({q}) from "{table}"').fetchone()
                col["min"], col["max"] = lo, hi
            elif ctype.upper().startswith("VARCHAR"):
                samples = con.execute(
                    f'select distinct {q} from "{table}" where {q} is not null limit 3'
                ).fetchall()
                col["samples"] = [str(s[0])[:40] for s in samples]
            out_cols.append(_col_line(col))
        return {"table": table, "row_count": n, "columns": out_cols}
    finally:
        con.close()


def sample_failing_rows(duckdb_path: Path, compiled_sql: str, limit: int = 3) -> list | None:
    try:
        con = _connect(duckdb_path)
        try:
            rows = con.execute(f"select * from ({compiled_sql}) limit {limit}").fetchall()
            return [[v if isinstance(v, (int, float, str, type(None))) else str(v) for v in r]
                    for r in rows]
        finally:
            con.close()
    except Exception:  # noqa: BLE001  sampling is best-effort; never block a diagnosis
        return None


# --------------------------------------------------------------------------- bundle

def build_evidence(
    target_dir: Path,
    *,
    duckdb_path: Path | None = None,
    source_table: str | None = "raw_tracks",
    baseline_models: Path | None = None,
    current_models: Path | None = None,
    diff_text: str | None = None,
) -> dict[str, Any]:
    run_results, manifest = load_artifacts(target_dir)
    summary, failures, skipped = summarise_results(run_results, manifest)

    if duckdb_path and duckdb_path.exists():
        for f in failures:
            if f["resource_type"] == "test" and f["status"] == "fail" and f.get("compiled_sql"):
                rows = sample_failing_rows(duckdb_path, f["_full_sql"])
                if rows:
                    f["sample_failing_rows"] = rows
            if f["resource_type"] == "test":
                # Test SQL is boilerplate; the test name, args and sample rows say more.
                f.pop("compiled_sql", None)
    for f in failures:
        f.pop("_full_sql", None)

    if diff_text is None and baseline_models and current_models:
        diff_text = code_diff(baseline_models, current_models)

    evidence: dict[str, Any] = {
        "run_summary": summary,
        "failures": failures,
        "skipped_downstream": skipped,
        "lineage": lineage(manifest),
        "recent_code_changes": diff_text or "(no changes to model code since last good run)",
    }
    if duckdb_path and duckdb_path.exists() and source_table:
        prof = profile_table(duckdb_path, source_table)
        evidence["source_profile"] = prof or f"(source table {source_table} not loaded)"
    return evidence
