"""An OpenAI-compatible chat model asked the same six questions, answering in JSON with stated probabilities."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from ..cache import JsonlCache, cache_key
from ..models import Answer, Decision, Update
from ..questions import DECISIONS, NOULS, RISK_LEVELS
from ..state import prepare_state
from .base import BackendError, CacheMiss, choice_confidence, normalise, noul_confidence, offline, score_confidence

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-flash-lite-latest"
# Assumed list price of the default model (USD per million tokens). Override with AI_PRICE_IN / AI_PRICE_OUT.
PRICE_IN = float(os.environ.get("AI_PRICE_IN", "0.10"))
PRICE_OUT = float(os.environ.get("AI_PRICE_OUT", "0.40"))

SYSTEM = "You review dependency-update pull requests for a software team. Reply with one JSON object and nothing else."


def build_prompt(state: dict[str, Any]) -> str:
    decisions = "\n".join(f'  "{k}": {v}' for k, v in DECISIONS.items())
    risk = "\n".join(f'  "{i}": {d}' for i, d in enumerate(RISK_LEVELS))
    nouls = "\n".join(f'  "{k}": {v}' for k, v in NOULS.items())
    return f"""Dependency update (JSON):
{json.dumps(state, ensure_ascii=False, indent=1)}

Answer these questions about the update.

1. "decision": should it be merged automatically? Give a probability for each option (they must sum to 1):
{decisions}

2. "risk": how risky is the upgrade for this repository? Give a probability for each level (they must sum to 1):
{risk}

3. For each statement below, give the probability (0 to 1) that it is true:
{nouls}

Return exactly this JSON shape:
{{"decision": {{"auto_merge": p, "merge_after_review": p, "hold": p}}, "risk": {{"0": p, "1": p, "2": p, "3": p}}, "breaking_in_notes": p, "breaking_affects_repo": p, "security_fix": p, "runtime_change": p}}"""


def parse_reply(text: str) -> dict[str, Answer]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise BackendError("the model reply contained no JSON object")
    data = json.loads(m.group(0))
    dprobs = normalise({k: float((data.get("decision") or {}).get(k, 0.0)) for k in DECISIONS})
    rmap = normalise({str(i): float((data.get("risk") or {}).get(str(i), 0.0)) for i in range(len(RISK_LEVELS))})
    rprobs = [rmap[str(i)] for i in range(len(RISK_LEVELS))]
    answers = {
        "decision": Answer("choice", max(dprobs, key=lambda k: dprobs[k]), choice_confidence(dprobs), dprobs),
        "risk": Answer("score", max(range(len(rprobs)), key=lambda i: rprobs[i]), score_confidence(rprobs), rmap),
    }
    for name in NOULS:
        p = min(1.0, max(0.0, float(data.get(name, 0.5))))
        answers[name] = Answer("noul", p, noul_confidence(p), {"yes": p, "no": 1 - p})
    return answers


class LlmBackend:
    name = "llm"

    def __init__(self, model: str | None = None, cache_path: Path | None = None, timeout: float = 60.0) -> None:
        self.model = model or os.environ.get("AI_MODEL", DEFAULT_MODEL)
        self.base_url = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        self.min_interval = max(2.5, float(os.environ.get("AI_MIN_INTERVAL", "2.5")))
        self.cache = JsonlCache(cache_path)
        self.timeout = timeout
        self._last_call = 0.0

    def _post(self, prompt: str) -> tuple[dict[str, Any], float]:
        key = os.environ.get("AI_API_KEY", "")
        if not key:
            raise BackendError("AI_API_KEY is not set")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(4):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            start = time.perf_counter()
            resp = httpx.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}, timeout=self.timeout)
            elapsed = (time.perf_counter() - start) * 1000
            self._last_call = time.monotonic()
            if resp.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise BackendError(f"model returned HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json(), elapsed
        raise BackendError("model did not answer after retries")

    def decide(self, update: Update) -> Decision:
        state, redactions = prepare_state(update)
        prompt = build_prompt(state)
        key = cache_key({"backend": self.name, "model": self.model, "prompt": prompt})
        hit = self.cache.get(key)
        cached = hit is not None
        if hit is None:
            if offline():
                raise CacheMiss(f"no cached model response for {update.package} {update.from_version} -> {update.to_version}")
            response, latency = self._post(prompt)
            hit = {"response": response, "latency_ms": round(latency, 1)}
            self.cache.put(key, hit)
        response = hit["response"]
        usage = response.get("usage", {})
        tin, tout = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        return Decision(
            backend=self.name,
            model=str(response.get("model", self.model)),
            answers=parse_reply(response["choices"][0]["message"]["content"] or ""),
            latency_ms=float(hit["latency_ms"]),
            input_tokens=tin,
            output_tokens=tout,
            cost_usd=(tin * PRICE_IN + tout * PRICE_OUT) / 1e6,
            cached=cached,
            redactions=redactions,
        )
