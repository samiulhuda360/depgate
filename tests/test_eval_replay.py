"""The committed evaluation replays from the recorded responses, with no network."""

from __future__ import annotations

import pytest

from depgate.evaluate import CACHE, evaluate, load_items, render_markdown


def test_dataset_is_consistent() -> None:
    items = load_items()
    assert len(items) >= 150
    for it in items:
        g = it.gold
        assert g["decision"] in ("auto_merge", "merge_after_review", "hold")
        if it.update.ci_status == "failure" or g["breaking_affects_repo"]:
            assert g["decision"] == "hold" and g["risk"] == 3, it.id
        if g["breaking_affects_repo"]:
            assert g["breaking_in_notes"], it.id
        if it.update.advisories:
            assert g["security_fix"], it.id


@pytest.mark.skipif(not (CACHE / "jev.jsonl").exists(), reason="no recorded Jev responses")
def test_offline_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPGATE_OFFLINE", "1")
    res = evaluate(["rules", "jev"])
    assert "jev" in res["backends"], "every labelled update must have a recorded Jev response"
    jev, rules = res["backends"]["jev"], res["backends"]["rules"]
    assert jev["policy_default"]["wrong_hold"] <= rules["policy_default"]["wrong_hold"]
    assert "# Evaluation results" in render_markdown(res)
