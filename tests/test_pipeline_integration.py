"""Runs real dbt builds. Skipped when dbt-duckdb is not installed."""

import importlib.util
import shutil
from pathlib import Path

import pytest

from incident_copilot.dbt_runner import run_scenario
from incident_copilot.schemas import load_scenarios

ROOT = Path(__file__).resolve().parents[1]


def _has_dbt_duckdb() -> bool:
    try:
        return shutil.which("dbt") is not None and importlib.util.find_spec("dbt.adapters.duckdb") is not None
    except ModuleNotFoundError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_dbt_duckdb(),
    reason="dbt-duckdb not installed (pip install -e '.[dbt]')",
)


def scenario(sid):
    return next(s for s in load_scenarios(ROOT / "scenarios/scenarios.yaml") if s.id == sid)


def test_schema_drift_breaks_staging():
    b = run_scenario(ROOT / "dbt_project", scenario("drift_energy_renamed"))
    ev = b["evidence"]
    assert b["dbt_exit_code"] != 0
    assert ev["failures"][0]["node"] == "stg_tracks"
    assert "energy" in ev["failures"][0]["message"]
    assert "int_tracks_enriched" in ev["skipped_downstream"]["models"]


def test_code_fault_shows_in_diff():
    b = run_scenario(ROOT / "dbt_project", scenario("sql_abs_loudness"))
    assert "abs(loudness)" in b["evidence"]["recent_code_changes"]
    assert b["evidence"]["failures"][0]["sample_failing_rows"]
