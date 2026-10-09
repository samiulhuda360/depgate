"""The decision-backend interface and the confidence formulas every backend shares."""

from __future__ import annotations

import os
from typing import Protocol

from ..models import Decision, Update


class BackendError(RuntimeError):
    """The backend could not produce a decision."""


class CacheMiss(BackendError):
    """Offline mode is on and the response is not in the cache."""


class Backend(Protocol):
    name: str
    model: str

    def decide(self, update: Update) -> Decision: ...


def offline() -> bool:
    """CI and replay runs set DEPGATE_OFFLINE=1 so no live API is ever called."""
    return os.environ.get("DEPGATE_OFFLINE", "") not in ("", "0", "false")


def choice_confidence(probs: dict[str, float]) -> float:
    """TypeSafe's Choice confidence: how far the top probability sits above an even split."""
    n = len(probs)
    if n < 2:
        return 1.0
    top = max(probs.values())
    return max(0.0, min(1.0, (top - 1 / n) / (1 - 1 / n)))


def score_confidence(probs: list[float]) -> float:
    """TypeSafe's Score confidence: 1 - (expected distance from the mode / expected distance under an even spread)."""
    n = len(probs)
    if n < 2:
        return 1.0
    mode = max(range(n), key=lambda i: probs[i])
    spread = sum(abs(i - mode) for i in range(n)) / n
    if spread == 0:
        return 1.0
    dist = sum(p * abs(i - mode) for i, p in enumerate(probs))
    return max(0.0, min(1.0, 1 - dist / spread))


def noul_confidence(p: float) -> float:
    """|2p - 1|: the Choice formula applied to a yes/no question."""
    return abs(2 * p - 1)


def normalise(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in values.values())
    if total <= 0:
        return {k: 1 / len(values) for k in values}
    return {k: max(0.0, v) / total for k, v in values.items()}
