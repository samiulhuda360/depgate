"""Jev (TypeSafe AI System One): all six questions in one typed call."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

from ..cache import JsonlCache, cache_key
from ..models import Answer, Decision, Update
from ..questions import NOULS, RISK_LEVELS, jev_questions
from ..state import prepare_state
from .base import BackendError, CacheMiss, choice_confidence, noul_confidence, offline, score_confidence

API_URL = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_M_INPUT = 0.042  # USD per million input tokens; output tokens are free
RETRY_STATUS = {429, 500, 502, 503, 529}


def parse_answers(raw: dict[str, Any]) -> dict[str, Answer]:
    """Turns a System One `answers` map into typed answers."""
    dec = raw["decision"]
    dprobs = {k: float(v) for k, v in dec["probabilities"].items()}
    answers = {"decision": Answer("choice", dec["choice"], float(dec.get("confidence", choice_confidence(dprobs))), dprobs)}
    risk = raw["risk"]
    rprobs = [float(risk["probabilities"].get(str(i), 0.0)) for i in range(len(RISK_LEVELS))]
    level = max(range(len(rprobs)), key=lambda i: rprobs[i])
    answers["risk"] = Answer("score", level, float(risk.get("confidence", score_confidence(rprobs))), {str(i): p for i, p in enumerate(rprobs)})
    for name in NOULS:
        p = float(raw[name]["noul"])
        answers[name] = Answer("noul", p, noul_confidence(p), {"yes": p, "no": 1 - p})
    return answers


class JevBackend:
    name = "jev"

    def __init__(self, model: str = "jev-latest", cache_path: Path | None = None, timeout: float = 30.0) -> None:
        self.model = model
        self.cache = JsonlCache(cache_path)
        self.timeout = timeout

    def request_body(self, update: Update) -> tuple[dict[str, Any], int]:
        state, redactions = prepare_state(update)
        return {"model": self.model, "state": state, "questions": jev_questions()}, redactions

    def _post(self, body: dict[str, Any]) -> tuple[dict[str, Any], float]:
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            raise BackendError("TYPESAFE_API_KEY is not set")
        delay = 1.0
        for attempt in range(5):
            start = time.perf_counter()
            resp = httpx.post(API_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout)
            elapsed = (time.perf_counter() - start) * 1000
            if resp.status_code in RETRY_STATUS and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code != 200:
                raise BackendError(f"Jev returned HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json(), elapsed
        raise BackendError("Jev did not answer after retries")

    def decide(self, update: Update) -> Decision:
        body, redactions = self.request_body(update)
        key = cache_key({"backend": self.name, **body})
        hit = self.cache.get(key)
        cached = hit is not None
        if hit is None:
            if offline():
                raise CacheMiss(f"no cached Jev response for {update.package} {update.from_version} -> {update.to_version}")
            response, latency = self._post(body)
            hit = {"response": response, "latency_ms": round(latency, 1)}
            self.cache.put(key, hit)
        response = hit["response"]
        usage = response.get("usage", {})
        tokens_in = int(usage.get("input_tokens", 0))
        return Decision(
            backend=self.name,
            model=str(response.get("model", self.model)),
            answers=parse_answers(response["answers"]),
            latency_ms=float(hit["latency_ms"]),
            input_tokens=tokens_in,
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=tokens_in * PRICE_PER_M_INPUT / 1e6,
            cached=cached,
            redactions=redactions,
        )
