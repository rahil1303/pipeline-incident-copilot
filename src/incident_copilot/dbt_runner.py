"""Run a scenario: copy the pipeline, inject faults, `dbt build`, collect evidence."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .evidence import build_evidence
from .faults import apply_faults
from .schemas import Scenario

IGNORE = shutil.ignore_patterns("target", "logs", "*.duckdb", "*.duckdb.wal", ".user.yml")


def ensure_deps(project: Path) -> None:
    """Install dbt packages once in the base project; scenario copies reuse them."""
    if not (project / "dbt_packages").exists():
        subprocess.run(["dbt", "deps", "--profiles-dir", "."], cwd=project, check=True,
                       capture_output=True, text=True)


def dbt_build(project: Path, duckdb_path: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "COPILOT_DUCKDB_PATH": str(duckdb_path), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    return subprocess.run(
        ["dbt", "build", "--profiles-dir", ".", "--no-use-colors"],
        cwd=project, env=env, capture_output=True, text=True, check=False,  # failures are expected
    )


def run_scenario(base_project: Path, scenario: Scenario, keep_dir: Path | None = None) -> dict[str, Any]:
    """Returns an evidence bundle with the scenario's metadata (label kept separate)."""
    ensure_deps(base_project)
    with tempfile.TemporaryDirectory(prefix=f"copilot_{scenario.id}_") as tmp:
        work = Path(tmp) / "project"
        shutil.copytree(base_project, work, ignore=IGNORE)
        apply_faults(work, scenario.distractors, seed_key=scenario.id + ":distractor")
        apply_faults(work, scenario.faults, seed_key=scenario.id)

        db = Path(tmp) / "warehouse.duckdb"
        t0 = time.perf_counter()
        proc = dbt_build(work, db)
        build_s = round(time.perf_counter() - t0, 2)

        if not (work / "target" / "run_results.json").exists():
            raise RuntimeError(f"dbt produced no run_results for {scenario.id}:\n{proc.stdout[-2000:]}")

        evidence = build_evidence(
            work / "target",
            duckdb_path=db,
            baseline_models=base_project / "models",
            current_models=work / "models",
        )
        if keep_dir:
            shutil.copytree(work, keep_dir / scenario.id, dirs_exist_ok=True)

    return {
        "scenario_id": scenario.id,
        "dbt_exit_code": proc.returncode,
        "dbt_build_seconds": build_s,
        "evidence": evidence,
        "label": scenario.label.__dict__,
    }


def write_bundle(bundle: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{bundle['scenario_id']}.json"
    path.write_text(json.dumps(bundle, indent=2, default=str))
    return path
