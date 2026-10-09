"""Small, dependency-free metrics: accuracy, F1, Brier score, reliability bins and percentiles."""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence


def accuracy(gold: Sequence[object], pred: Sequence[object]) -> float:
    return sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold) if gold else 0.0


def prf(gold: Sequence[bool], pred: Sequence[bool]) -> tuple[float, float, float]:
    """Precision, recall and F1 of the positive class."""
    tp = sum(g and p for g, p in zip(gold, pred, strict=True))
    fp = sum((not g) and p for g, p in zip(gold, pred, strict=True))
    fn = sum(g and not p for g, p in zip(gold, pred, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def macro_f1(gold: Sequence[object], pred: Sequence[object], labels: Sequence[object]) -> float:
    scores = [prf([g == c for g in gold], [p == c for p in pred])[2] for c in labels]
    return sum(scores) / len(scores) if scores else 0.0


def brier(probs: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Mean squared gap between a stated probability and what happened (0 is perfect, 0.25 is a coin flip)."""
    return sum((p - float(o)) ** 2 for p, o in zip(probs, outcomes, strict=True)) / len(probs) if probs else 0.0


def reliability(
    probs: Sequence[float], outcomes: Sequence[bool], edges: Sequence[float] = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)
) -> list[tuple[str, int, float, float]]:
    """Rows of (bin, count, mean stated probability, observed frequency)."""
    rows = []
    for lo, hi in itertools.pairwise(edges):
        idx = [i for i, p in enumerate(probs) if lo <= p < hi]
        if not idx:
            rows.append((f"{lo:.1f}-{min(hi, 1.0):.1f}", 0, math.nan, math.nan))
            continue
        rows.append((f"{lo:.1f}-{min(hi, 1.0):.1f}", len(idx), sum(probs[i] for i in idx) / len(idx), sum(outcomes[i] for i in idx) / len(idx)))
    return rows


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
