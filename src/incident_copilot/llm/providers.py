"""LLM providers behind one small interface, all free to use.

Every hosted provider here speaks the OpenAI chat-completions protocol, so one
HTTP client covers them all; only base URL, key and model differ.

    groq        free tier, no card            GROQ_API_KEY
    gemini      Google AI Studio free tier    GEMINI_API_KEY
    openrouter  ':free' models                OPENROUTER_API_KEY
    ollama      local models, unlimited       (no key; needs `ollama serve`)

Spec strings: "groq", "groq:openai/gpt-oss-20b", "ollama:qwen2.5:7b".
A comma-separated list ("groq,gemini,ollama") builds a fallback chain: free
tiers rate-limit and occasionally retire models, so the agent moves on to the
next provider instead of failing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

PRESETS: dict[str, dict[str, str | None]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "openai/gpt-oss-120b",
        # Free tier allows ~8k tokens/min; one diagnosis is ~2k tokens incl. reasoning.
        "min_interval_s": "15",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
        "min_interval_s": "5",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "min_interval_s": "4",
    },
    "ollama": {
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "key_env": None,
        "model_env": "OLLAMA_MODEL",
        "default_model": "llama3.1:8b",
        "min_interval_s": "0",
    },
}


class ProviderError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Provider:
    name = "base"
    model = ""

    def complete(self, messages: list[dict], *, json_mode: bool = True) -> Completion:
        raise NotImplementedError


class OpenAICompatible(Provider):
    def __init__(self, name: str, base_url: str, model: str, api_key: str | None = None,
                 *, timeout: float = 90.0, max_retries: int = 4, min_interval_s: float = 0.0):
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key = api_key
        self.timeout, self.max_retries = timeout, max_retries
        # Spacing between calls keeps us under free-tier requests/tokens per minute.
        self.min_interval_s = min_interval_s
        self._last_call = 0.0

    def _wait_turn(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval_s:
            time.sleep(self.min_interval_s - gap)
        self._last_call = time.monotonic()

    def complete(self, messages: list[dict], *, json_mode: bool = True) -> Completion:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict = {"model": self.model, "messages": messages, "temperature": 0}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err = ""
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            t0 = time.perf_counter()
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=payload,
                               headers=headers, timeout=self.timeout)
            except httpx.HTTPError as e:
                last_err = f"network error: {e}"
                time.sleep(min(2 ** attempt, 20))
                continue
            latency = time.perf_counter() - t0

            if r.status_code == 200:
                data = r.json()
                usage = data.get("usage") or {}
                return Completion(
                    text=data["choices"][0]["message"]["content"] or "",
                    provider=self.name, model=self.model, latency_s=round(latency, 3),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code == 400 and "response_format" in payload:
                payload.pop("response_format")  # some models lack JSON mode; prompt still asks for JSON
                continue
            if r.status_code == 429 or r.status_code >= 500:
                retry_after = r.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() \
                    else min(2 ** (attempt + 1), 60)
                time.sleep(delay)
                continue
            break  # 401/403/404 etc: retrying will not help
        raise ProviderError(f"{self.name}:{self.model} failed: {last_err}")


class FallbackChain(Provider):
    """Try providers in order; return the first success."""

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError("empty provider chain")
        self.providers = providers
        self.name = ",".join(p.name for p in providers)
        self.model = providers[0].model

    def complete(self, messages: list[dict], *, json_mode: bool = True) -> Completion:
        errors = []
        for p in self.providers:
            try:
                return p.complete(messages, json_mode=json_mode)
            except ProviderError as e:
                errors.append(str(e))
        raise ProviderError("all providers failed:\n  " + "\n  ".join(errors))


def make_provider(spec: str) -> Provider:
    """Build a provider (or fallback chain) from a spec string."""
    parts = [s.strip() for s in spec.split(",") if s.strip()]
    if len(parts) > 1:
        return FallbackChain([make_provider(p) for p in parts])

    name, _, model = parts[0].partition(":")
    if name not in PRESETS:
        raise ValueError(f"unknown provider {name!r}; choose from {sorted(PRESETS)} "
                         "(or use 'baseline' in the agent/eval commands)")
    preset = PRESETS[name]
    model = model or os.environ.get(preset["model_env"] or "", "") or preset["default_model"]
    key = None
    if preset["key_env"]:
        key = os.environ.get(preset["key_env"])
        if not key:
            raise ProviderError(f"{preset['key_env']} is not set (see .env.example)")
    interval = float(os.environ.get("COPILOT_MIN_INTERVAL_S") or preset.get("min_interval_s") or 0)
    return OpenAICompatible(name, preset["base_url"], model, key, min_interval_s=interval)
