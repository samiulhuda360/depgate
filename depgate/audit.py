"""Append-only JSONL audit log: one line per decision, with what was asked, answered and done."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import Decision, Update
from .policy import Outcome


def audit_record(update: Update, decision: Decision, outcome: Outcome, dry_run: bool) -> dict[str, object]:
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo": update.repo,
        "pr": update.number,
        "head_sha": update.head_sha,
        "package": update.package,
        "ecosystem": update.ecosystem,
        "from": update.from_version,
        "to": update.to_version,
        "jump": update.jump,
        "ci_status": update.ci_status,
        "advisories": [a.get("ghsa_id", "") for a in update.advisories],
        "backend": decision.backend,
        "model": decision.model,
        "answers": {k: {"value": a.value, "confidence": round(a.confidence, 4)} for k, a in decision.answers.items()},
        "action": outcome.action,
        "outcome": asdict(outcome),
        "latency_ms": round(decision.latency_ms, 1),
        "input_tokens": decision.input_tokens,
        "cost_usd": round(decision.cost_usd, 8),
        "redactions": decision.redactions,
        "dry_run": dry_run,
    }


def write_audit(path: str | Path, record: dict[str, object]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
