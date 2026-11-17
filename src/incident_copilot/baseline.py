"""Rule-based baseline: what a few regexes and if-statements can do without an LLM.

It is the floor the LLM has to beat. It reads error messages and test types
well, but it cannot tell a harmless code edit from a real bug, so it treats
any code change as the cause.
"""

from __future__ import annotations

import re

from .schemas import SOURCE_NODE, Diagnosis

_REF_COL = re.compile(r'Referenced column "([^"]+)" not found')
_SOURCE_COL = re.compile(r"source column (\w+)")


def _changed_models(diff: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/models/(?:.*/)?(\w+)\.sql", diff, flags=re.MULTILINE)


def diagnose_baseline(evidence: dict) -> Diagnosis:
    failures = evidence.get("failures") or []
    diff = evidence.get("recent_code_changes", "")
    changed = _changed_models(diff)

    if not failures:
        return Diagnosis("out_of_range", SOURCE_NODE, None, "no failures found",
                         provider="baseline", model="rules", parse_ok=False)

    f = failures[0]
    msg = f.get("message", "")
    node = f.get("node", "")

    def done(cat, root, col, why):
        return Diagnosis(cat, root, col, why, provider="baseline", model="rules")

    if f.get("resource_type") == "model" or f.get("status") == "error":
        m = _REF_COL.search(msg)
        if m:
            if changed:
                return done("sql_logic_error", changed[0], m.group(1),
                            "missing column and the model code changed")
            return done("schema_drift", SOURCE_NODE, m.group(1),
                        "column missing from source, no code changes")
        if any(s in msg for s in ("Conversion Error", "Could not convert", "VARCHAR")):
            col = _SOURCE_COL.search(msg)
            return done("type_mismatch", SOURCE_NODE, col.group(1) if col else None,
                        "type conversion error")
        return done("sql_logic_error", changed[0] if changed else node, None, "unrecognised error")

    test = f.get("test", "")
    col = f.get("column")
    if changed:
        return done("sql_logic_error", changed[0], col, "test failed after a code change")
    if test in {"not_null", "completeness_above"}:
        return done("null_values", SOURCE_NODE, col, f"{test} failed")
    return done("out_of_range", SOURCE_NODE, col, f"{test} failed")
