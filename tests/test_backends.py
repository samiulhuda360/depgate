from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from depgate.backends import BackendError, CacheMiss, JevBackend, LlmBackend, RulesBackend, get_backend
from depgate.backends.base import choice_confidence, score_confidence
from depgate.backends.llm import parse_reply
from depgate.models import Update
from depgate.questions import jev_questions

JEV_RESPONSE = {
    "model": "jev-test",
    "answers": {
        "decision": {
            "type": "choice",
            "choice": "auto_merge",
            "confidence": 0.9,
            "probabilities": {"auto_merge": 0.933, "merge_after_review": 0.05, "hold": 0.017},
        },
        "risk": {"type": "score", "score": 0.1, "confidence": 0.9, "legend": {}, "probabilities": {"0": 0.9, "1": 0.1, "2": 0.0, "3": 0.0}},
        "breaking_in_notes": {"type": "noul", "noul": 0.03},
        "breaking_affects_repo": {"type": "noul", "noul": 0.02},
        "security_fix": {"type": "noul", "noul": 0.04},
        "runtime_change": {"type": "noul", "noul": 0.01},
    },
    "usage": {"input_tokens": 1000, "output_tokens": 150},
}


def test_confidence_formulas_match_the_docs() -> None:
    assert choice_confidence({"a": 0.6, "b": 0.3, "c": 0.1}) == pytest.approx(0.4)
    assert choice_confidence({"a": 0.6, "b": 0.2, "c": 0.2}) == pytest.approx(0.4)
    assert score_confidence([0.0, 0.5, 0.5]) == pytest.approx(0.25)
    assert score_confidence([0.5, 0.0, 0.5]) == pytest.approx(0.0)


def test_questions_shape() -> None:
    q = jev_questions()
    assert q["decision"]["type"] == "choice" and set(q["decision"]["criteria"]) == {"auto_merge", "merge_after_review", "hold"}
    assert q["risk"]["type"] == "score" and len(q["risk"]["criteria"]) == 4
    assert {k for k, v in q.items() if v["type"] == "noul"} == {"breaking_in_notes", "breaking_affects_repo", "security_fix", "runtime_change"}


def test_jev_calls_once_then_replays(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, update: Update) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> httpx.Response:
        calls.append(json)
        assert headers["Authorization"] == "Bearer test-key-not-real"
        return httpx.Response(200, json=JEV_RESPONSE)

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
    monkeypatch.delenv("DEPGATE_OFFLINE", raising=False)
    monkeypatch.setattr(httpx, "post", fake_post)
    backend = JevBackend(cache_path=tmp_path / "jev.jsonl")
    d = backend.decide(update)
    assert d.decision == "auto_merge" and d.risk == 0 and not d.cached
    assert d.input_tokens == 1000 and d.cost_usd == pytest.approx(1000 * 0.042 / 1e6)
    assert calls[0]["model"] == "jev-latest" and calls[0]["state"]["package"] == "axios"
    again = JevBackend(cache_path=tmp_path / "jev.jsonl").decide(update)
    assert again.cached and len(calls) == 1


def test_offline_mode_never_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, update: Update) -> None:
    monkeypatch.setenv("DEPGATE_OFFLINE", "1")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("network call in offline mode"))
    with pytest.raises(CacheMiss):
        JevBackend(cache_path=tmp_path / "jev.jsonl").decide(update)


def test_jev_without_key_errors(monkeypatch: pytest.MonkeyPatch, update: Update) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("DEPGATE_OFFLINE", raising=False)
    with pytest.raises(BackendError):
        JevBackend().decide(update)


def test_llm_reply_parsing_normalises() -> None:
    reply = json.dumps(
        {
            "decision": {"auto_merge": 2, "merge_after_review": 1, "hold": 1},
            "risk": {"0": 0.1, "1": 0.7, "2": 0.2, "3": 0},
            "breaking_in_notes": 0.2,
            "breaking_affects_repo": 0.1,
            "security_fix": 1.4,
            "runtime_change": 0,
        }
    )
    a = parse_reply("```json\n" + reply + "\n```")
    assert a["decision"].value == "auto_merge" and a["decision"].probabilities["auto_merge"] == pytest.approx(0.5)
    assert a["risk"].value == 1
    assert a["security_fix"].value == 1.0


def test_llm_uses_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, update: Update) -> None:
    content = json.dumps({"decision": {"auto_merge": 0.9, "merge_after_review": 0.05, "hold": 0.05}, "risk": {"0": 1}})
    response = {"model": "llm-test", "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 800, "completion_tokens": 60}}
    monkeypatch.setenv("AI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("DEPGATE_OFFLINE", raising=False)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=response))
    b = LlmBackend(cache_path=tmp_path / "llm.jsonl")
    b.min_interval = 0
    d = b.decide(update)
    assert d.decision == "auto_merge" and d.output_tokens == 60
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("should replay"))
    assert LlmBackend(cache_path=tmp_path / "llm.jsonl").decide(update).cached


def test_rules_baseline_is_semver_only(update: Update) -> None:
    rules = RulesBackend()
    assert rules.decide(update).decision == "auto_merge"
    update.jump = "major"
    assert rules.decide(update).decision == "hold"
    update.jump = ""
    update.from_version, update.to_version = "1.9.0", "1.10.0"
    assert rules.decide(update).decision == "auto_merge"


def test_auto_backend_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert get_backend("auto").name == "rules"
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-not-real")
    assert get_backend("auto").name == "jev"
