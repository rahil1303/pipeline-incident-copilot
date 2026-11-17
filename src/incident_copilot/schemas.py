"""Shared data structures: incident categories, scenarios, diagnoses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# The fixed set of root-cause categories the copilot chooses from.
# Keeping this closed makes diagnoses scoreable.
CATEGORIES: dict[str, str] = {
    "out_of_range": (
        "Source values fall outside the contract bounds, e.g. an upstream unit or "
        "scale change (0-1 became 0-100) or corrupt measurements."
    ),
    "null_values": (
        "Required fields arrive empty or completeness drops below threshold in the "
        "source data."
    ),
    "schema_drift": (
        "The source schema changed: a column was renamed, dropped or added, so "
        "models referencing it break."
    ),
    "type_mismatch": (
        "A source column changed data type, e.g. numbers now arrive as strings "
        "with units, so casts or comparisons fail."
    ),
    "sql_logic_error": (
        "A bug was introduced in dbt model code (typo, removed filter, wrong ref "
        "or join), not in the data itself."
    ),
}

SOURCE_NODE = "raw_tracks"


@dataclass
class Label:
    """Ground truth for a scenario."""

    category: str
    root_cause_node: str
    column: str | None = None

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")


@dataclass
class Scenario:
    id: str
    description: str
    faults: list[dict[str, Any]]
    label: Label
    # Harmless code edits added to make the case realistic (real incidents rarely
    # come with a clean git history). They must not change pipeline behaviour.
    distractors: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Scenario:
        return cls(
            id=d["id"],
            description=d["description"],
            faults=d["faults"],
            label=Label(**d["label"]),
            distractors=d.get("distractors", []),
        )


@dataclass
class Diagnosis:
    category: str
    root_cause_node: str
    column: str | None
    explanation: str = ""
    suggested_fix: str = ""
    confidence: float | None = None
    # Bookkeeping, filled by the agent
    provider: str = ""
    model: str = ""
    latency_s: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    parse_ok: bool = True
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_node(name: str | None) -> str:
    """Map 'model.spotify_pipeline.stg_tracks', 'seed...raw_tracks' etc to a bare name."""
    if not name:
        return ""
    name = name.strip().lower()
    return name.split(".")[-1]


def normalise_column(name: str | None) -> str | None:
    if name is None:
        return None
    name = str(name).strip().lower()
    return name or None


def load_scenarios(path) -> list[Scenario]:
    from pathlib import Path

    import yaml

    data = yaml.safe_load(Path(path).read_text())
    return [Scenario.from_dict(s) for s in data["scenarios"]]
