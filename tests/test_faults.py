import csv
import random
import shutil
from pathlib import Path

import pytest

from incident_copilot import faults

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    (p / "seeds").mkdir(parents=True)
    shutil.copy(ROOT / "dbt_project/seeds/raw_tracks.csv", p / "seeds/raw_tracks.csv")
    shutil.copytree(ROOT / "dbt_project/models", p / "models")
    return p


def rows(p):
    with (p / "seeds/raw_tracks.csv").open() as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def test_scale_column_all_rows(project):
    _, before = rows(project)
    faults.scale_column(project, random.Random(0), "energy", 100)
    _, after = rows(project)
    assert float(after[0]["energy"]) == pytest.approx(float(before[0]["energy"]) * 100)


def test_null_column_fraction(project):
    faults.null_column(project, random.Random(0), "danceability", fraction=0.1)
    _, r = rows(project)
    assert sum(1 for x in r if x["danceability"] == "") == round(len(r) * 0.1)


def test_rename_and_drop(project):
    faults.rename_column(project, random.Random(0), "tempo", "bpm")
    faults.drop_column(project, random.Random(0), "valence")
    header, r = rows(project)
    assert "bpm" in header and "tempo" not in header and "valence" not in header
    assert r[0]["bpm"]


def test_replace_in_model(project):
    faults.replace_in_model(project, random.Random(0), "stg_tracks", "AND tempo > 0", "")
    assert "tempo > 0" not in (project / "models/staging/stg_tracks.sql").read_text()


def test_unknown_column_raises(project):
    with pytest.raises(faults.FaultError):
        faults.null_column(project, random.Random(0), "nope")


def test_apply_faults_is_deterministic(project, tmp_path):
    other = tmp_path / "other"
    shutil.copytree(project, other)
    spec = [{"type": "null_column", "column": "energy", "fraction": 0.2}]
    faults.apply_faults(project, spec, "same-id")
    faults.apply_faults(other, spec, "same-id")
    assert rows(project) == rows(other)
