"""The semver-only baseline most teams start with: patch and minor bumps auto-merge, major bumps are held."""

from __future__ import annotations

import time

from ..models import Answer, Decision, Update
from ..versions import parse_version, semver_jump
from .base import choice_confidence, noul_confidence, score_confidence

DECISION_BY_JUMP = {"patch": "auto_merge", "minor": "auto_merge", "major": "hold"}
RISK_BY_JUMP = {"patch": 0, "minor": 1, "major": 3}


def jump_of(update: Update) -> str:
    if update.jump:
        return update.jump
    old, new = parse_version(update.from_version), parse_version(update.to_version)
    return semver_jump(old, new) if old and new else "major"


class RulesBackend:
    name = "rules"
    model = "semver-rules"

    def decide(self, update: Update) -> Decision:
        start = time.perf_counter()
        jump = jump_of(update)
        choice = DECISION_BY_JUMP.get(jump, "hold")
        dprobs = {k: (1.0 if k == choice else 0.0) for k in ("auto_merge", "merge_after_review", "hold")}
        level = RISK_BY_JUMP.get(jump, 3)
        rprobs = [0.94 if i == level else 0.02 for i in range(4)]
        major = jump == "major"
        nouls = {
            "breaking_in_notes": 0.7 if major else 0.1,
            "breaking_affects_repo": 0.6 if major else 0.1,
            "security_fix": 0.95 if update.advisories else 0.05,
            "runtime_change": 0.3 if major else 0.05,
        }
        answers = {
            "decision": Answer("choice", choice, choice_confidence(dprobs), dprobs),
            "risk": Answer("score", level, score_confidence(rprobs), {str(i): p for i, p in enumerate(rprobs)}),
        }
        for name, p in nouls.items():
            answers[name] = Answer("noul", p, noul_confidence(p), {"yes": p, "no": 1 - p})
        return Decision(backend=self.name, model=self.model, answers=answers, latency_ms=(time.perf_counter() - start) * 1000)
