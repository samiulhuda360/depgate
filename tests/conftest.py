from __future__ import annotations

import pytest

from depgate.backends.base import choice_confidence, noul_confidence, score_confidence
from depgate.models import Answer, Decision, Update


def make_decision(choice: str = "auto_merge", conf_top: float = 0.95, risk: int = 0, **nouls: float) -> Decision:
    others = [k for k in ("auto_merge", "merge_after_review", "hold") if k != choice]
    dprobs = {choice: conf_top, others[0]: (1 - conf_top) / 2, others[1]: (1 - conf_top) / 2}
    rprobs = [0.94 if i == risk else 0.02 for i in range(4)]
    answers = {
        "decision": Answer("choice", choice, choice_confidence(dprobs), dprobs),
        "risk": Answer("score", risk, score_confidence(rprobs), {str(i): p for i, p in enumerate(rprobs)}),
    }
    defaults = {"breaking_in_notes": 0.05, "breaking_affects_repo": 0.05, "security_fix": 0.05, "runtime_change": 0.05}
    defaults.update(nouls)
    for name, p in defaults.items():
        answers[name] = Answer("noul", p, noul_confidence(p), {"yes": p, "no": 1 - p})
    return Decision(backend="fake", model="fake-1", answers=answers, latency_ms=12.0)


class FakeBackend:
    name = "fake"
    model = "fake-1"

    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        self.seen: list[Update] = []

    def decide(self, update: Update) -> Decision:
        self.seen.append(update)
        return self.decision


@pytest.fixture
def update() -> Update:
    return Update(
        package="axios",
        ecosystem="npm",
        from_version="1.6.0",
        to_version="1.6.1",
        jump="patch",
        release_notes="## v1.6.1\n- fix: `formDataToJSON` handles nested arrays\n- docs: typo",
        ci_status="success",
        usage=["src/http.js:1: const axios = require('axios');", "src/http.js:4: const body = axios.formDataToJSON(form);"],
        repo="example/orders-api",
        number=7,
        head_sha="abc123",
        node_id="PR_node",
        author="dependabot[bot]",
    )
