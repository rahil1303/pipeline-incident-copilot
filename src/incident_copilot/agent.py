"""The diagnosis agent: evidence bundle in, structured diagnosis out."""

from __future__ import annotations

import json
import re
import time

from .baseline import diagnose_baseline
from .llm import Provider, ProviderError, make_provider
from .prompts import build_messages
from .schemas import CATEGORIES, Diagnosis

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_diagnosis(text: str) -> dict | None:
    """Pull the JSON object out of a model reply, tolerating code fences and chatter."""
    m = _JSON_BLOCK.search(text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Agent:
    def __init__(self, provider: str | Provider = "baseline"):
        self.spec = provider if isinstance(provider, str) else provider.name
        self.provider = None if provider == "baseline" else (
            make_provider(provider) if isinstance(provider, str) else provider)

    def diagnose(self, evidence: dict) -> Diagnosis:
        if self.provider is None:
            t0 = time.perf_counter()
            d = diagnose_baseline(evidence)
            d.latency_s = round(time.perf_counter() - t0, 4)
            return d

        try:
            c = self.provider.complete(build_messages(evidence))
        except ProviderError as e:
            return Diagnosis("", "", None, provider=self.spec, parse_ok=False, raw=str(e))

        data = parse_diagnosis(c.text)
        ok = bool(data) and data.get("category") in CATEGORIES
        data = data or {}
        conf = data.get("confidence")
        return Diagnosis(
            category=str(data.get("category", "")),
            root_cause_node=str(data.get("root_cause_node", "")),
            column=data.get("column") if data.get("column") not in ("", "null") else None,
            explanation=str(data.get("explanation", "")),
            suggested_fix=str(data.get("suggested_fix", "")),
            confidence=float(conf) if isinstance(conf, (int, float)) else None,
            provider=c.provider, model=c.model, latency_s=c.latency_s,
            prompt_tokens=c.prompt_tokens, completion_tokens=c.completion_tokens,
            parse_ok=ok, raw=c.text,
        )
