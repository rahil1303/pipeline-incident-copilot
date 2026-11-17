import json
from pathlib import Path

import httpx
import pytest

from incident_copilot.agent import Agent, parse_diagnosis
from incident_copilot.baseline import diagnose_baseline
from incident_copilot.evaluate import run_eval, score, to_markdown
from incident_copilot.llm import Completion, FallbackChain, OpenAICompatible, Provider, ProviderError
from incident_copilot.prompts import build_messages
from incident_copilot.schemas import Diagnosis, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def bundle(sid):
    return json.loads((EVIDENCE / f"{sid}.json").read_text())


# ------------------------------------------------------------------ parsing

def test_parse_handles_code_fences_and_chatter():
    text = 'Sure!\n```json\n{"category": "schema_drift", "column": "energy"}\n```'
    assert parse_diagnosis(text)["category"] == "schema_drift"


def test_parse_rejects_garbage():
    assert parse_diagnosis("no json here") is None
    assert parse_diagnosis("{broken") is None


# ------------------------------------------------------------------ agent with fake provider

class FakeProvider(Provider):
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, messages, *, json_mode=True):
        self.calls.append(messages)
        return Completion(self.reply, self.name, self.model, 0.1, 900, 80)


def test_agent_parses_llm_reply():
    reply = json.dumps({"category": "out_of_range", "root_cause_node": "raw_tracks",
                        "column": "energy", "explanation": "x", "suggested_fix": "y",
                        "confidence": 0.9})
    fake = FakeProvider(reply)
    d = Agent(fake).diagnose(bundle("oor_energy_percent")["evidence"])
    assert d.parse_ok and d.category == "out_of_range" and d.prompt_tokens == 900
    # Evidence reaches the model, compactly serialised
    assert "in_range" in fake.calls[0][1]["content"]


def test_agent_flags_invalid_category():
    d = Agent(FakeProvider('{"category": "aliens"}')).diagnose({"failures": []})
    assert not d.parse_ok


def test_prompt_lists_every_category():
    system = build_messages({})[0]["content"]
    for cat in ["out_of_range", "null_values", "schema_drift", "type_mismatch", "sql_logic_error"]:
        assert cat in system


# ------------------------------------------------------------------ providers (HTTP mocked)

def _resp(status, body=None, headers=None):
    return httpx.Response(status, json=body or {}, headers=headers or {},
                          request=httpx.Request("POST", "http://x"))


OK_BODY = {"choices": [{"message": {"content": '{"category":"null_values"}'}}],
           "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def test_provider_retries_on_429(monkeypatch):
    replies = [_resp(429, headers={"retry-after": "0"}), _resp(200, OK_BODY)]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: replies.pop(0))
    c = OpenAICompatible("t", "http://x", "m").complete([{"role": "user", "content": "hi"}])
    assert c.prompt_tokens == 10 and not replies


def test_provider_drops_json_mode_on_400(monkeypatch):
    seen = []

    def post(*a, json=None, **k):
        seen.append("response_format" in json)
        return _resp(400) if json.get("response_format") else _resp(200, OK_BODY)

    monkeypatch.setattr(httpx, "post", post)
    OpenAICompatible("t", "http://x", "m").complete([])
    assert seen == [True, False]


def test_provider_does_not_retry_auth_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or _resp(401))
    with pytest.raises(ProviderError):
        OpenAICompatible("t", "http://x", "m").complete([])
    assert len(calls) == 1


def test_fallback_chain_uses_next_provider():
    class Broken(Provider):
        name = "broken"

        def complete(self, messages, *, json_mode=True):
            raise ProviderError("down")

    good = FakeProvider('{"category":"schema_drift"}')
    assert FallbackChain([Broken(), good]).complete([]).provider == "fake"


# ------------------------------------------------------------------ baseline + scoring

def test_baseline_reads_schema_drift():
    d = diagnose_baseline(bundle("drift_energy_renamed")["evidence"])
    assert (d.category, d.root_cause_node, d.column) == ("schema_drift", "raw_tracks", "energy")


def test_baseline_is_fooled_by_harmless_edit():
    # The documented weakness the LLM should overcome.
    d = diagnose_baseline(bundle("null_energy_small")["evidence"])
    assert d.category == "sql_logic_error"


def test_score_column_optional():
    label = {"category": "schema_drift", "root_cause_node": "raw_tracks", "column": "Energy"}
    d = Diagnosis("schema_drift", "seed.spotify_pipeline.raw_tracks", "energy")
    assert score(d, label)["fully_correct"]


def test_every_scenario_has_evidence():
    ids = {s.id for s in load_scenarios(ROOT / "scenarios/scenarios.yaml")}
    assert ids == {p.stem for p in EVIDENCE.glob("*.json")}


def test_baseline_eval_end_to_end():
    report = run_eval("baseline", EVIDENCE, progress=False)
    assert report["n"] == 20
    assert 0 < report["metrics"]["fully_correct"] < 1
    assert "| Scenario |" in to_markdown(report)
