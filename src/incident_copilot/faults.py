"""Fault injectors: break a copy of the pipeline in known, labelled ways.

Each fault is a dict with a ``type`` key plus parameters, so scenarios can be
written in YAML. Data faults edit the seed CSV (simulating a bad upstream
delivery); code faults edit model SQL (simulating a bad commit).
"""

from __future__ import annotations

import csv
import random
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

SEED_REL = Path("seeds/raw_tracks.csv")
MODELS_REL = Path("models")


class FaultError(RuntimeError):
    pass


# --------------------------------------------------------------------------- csv io

def _read(project: Path) -> tuple[list[str], list[dict[str, str]]]:
    with (project / SEED_REL).open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _write(project: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with (project / SEED_REL).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _pick(rows: list, fraction: float, rng: random.Random) -> list[int]:
    k = max(1, round(len(rows) * fraction))
    return sorted(rng.sample(range(len(rows)), min(k, len(rows))))


def _need(header: list[str], column: str) -> None:
    if column not in header:
        raise FaultError(f"column {column!r} not in seed header")


# --------------------------------------------------------------------------- data faults

def scale_column(project: Path, rng: random.Random, column: str, factor: float,
                 fraction: float = 1.0) -> None:
    """Multiply values, e.g. a 0-1 score exported as a percentage."""
    header, rows = _read(project)
    _need(header, column)
    for i in _pick(rows, fraction, rng):
        rows[i][column] = str(round(float(rows[i][column]) * factor, 4))
    _write(project, header, rows)


def set_value(project: Path, rng: random.Random, column: str, value: Any,
              fraction: float = 0.05) -> None:
    """Overwrite a fraction of values with a fixed (usually invalid) value."""
    header, rows = _read(project)
    _need(header, column)
    for i in _pick(rows, fraction, rng):
        rows[i][column] = str(value)
    _write(project, header, rows)


def negate_column(project: Path, rng: random.Random, column: str, fraction: float = 1.0) -> None:
    """Flip the sign, e.g. loudness exported as positive attenuation."""
    header, rows = _read(project)
    _need(header, column)
    for i in _pick(rows, fraction, rng):
        rows[i][column] = str(-float(rows[i][column]))
    _write(project, header, rows)


def null_column(project: Path, rng: random.Random, column: str, fraction: float = 0.1) -> None:
    """Blank out values (an upstream join or extract silently dropping data)."""
    header, rows = _read(project)
    _need(header, column)
    for i in _pick(rows, fraction, rng):
        rows[i][column] = ""
    _write(project, header, rows)


def rename_column(project: Path, rng: random.Random, old: str, new: str) -> None:
    header, rows = _read(project)
    _need(header, old)
    header = [new if h == old else h for h in header]
    for r in rows:
        r[new] = r.pop(old)
    _write(project, header, rows)


def drop_column(project: Path, rng: random.Random, column: str) -> None:
    header, rows = _read(project)
    _need(header, column)
    _write(project, [h for h in header if h != column], rows)


def stringify_column(project: Path, rng: random.Random, column: str, template: str,
                     fraction: float = 0.3) -> None:
    """Turn numbers into strings, e.g. '120.5 bpm'. Column becomes VARCHAR on load."""
    header, rows = _read(project)
    _need(header, column)
    for i in _pick(rows, fraction, rng):
        rows[i][column] = template.format(v=rows[i][column])
    _write(project, header, rows)


# --------------------------------------------------------------------------- code faults

def replace_in_model(project: Path, rng: random.Random, model: str, old: str, new: str,
                     count: int = 1) -> None:
    """Edit model SQL. Used for both real bugs and harmless distractor edits."""
    matches = list((project / MODELS_REL).rglob(f"{model}.sql"))
    if not matches:
        raise FaultError(f"model {model!r} not found")
    path = matches[0]
    sql = path.read_text()
    if old not in sql:
        raise FaultError(f"text {old!r} not found in {path.name}")
    path.write_text(sql.replace(old, new, count))


FAULTS: dict[str, Callable[..., None]] = {
    f.__name__: f
    for f in [scale_column, set_value, negate_column, null_column, rename_column,
              drop_column, stringify_column, replace_in_model]
}


def apply_faults(project: Path, faults: list[dict[str, Any]], seed_key: str) -> None:
    """Apply faults in order. Randomness is seeded by scenario id, so runs repeat exactly."""
    rng = random.Random(zlib.crc32(seed_key.encode()))
    for spec in faults:
        spec = dict(spec)
        kind = spec.pop("type")
        if kind not in FAULTS:
            raise FaultError(f"unknown fault type {kind!r}; known: {sorted(FAULTS)}")
        FAULTS[kind](project, rng, **spec)
