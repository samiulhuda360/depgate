"""Per-repository policy, read from `.github/depgate.yml`. Every key is optional."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = ".github/depgate.yml"


@dataclass
class AutoMerge:
    enabled: bool = True
    min_confidence: float = 0.8
    max_risk: int = 1
    allow_major: bool = False
    require_ci: bool = True
    approve: bool = True
    merge_method: str = "SQUASH"  # MERGE | SQUASH | REBASE
    ignore: list[str] = field(default_factory=list)


@dataclass
class Labels:
    auto_merge: str = "depgate:auto-merge"
    review: str = "depgate:review"
    hold: str = "depgate:hold"
    needs_human: str = "depgate:needs-human"
    security: str = "security-update"
    priority: str = "priority:high"
    breaking: str = "breaking-change"
    runtime: str = "runtime-change"


@dataclass
class Notify:
    events: list[str] = field(default_factory=lambda: ["hold", "security"])
    slack_webhook_env: str = "DEPGATE_SLACK_WEBHOOK"
    teams_webhook_env: str = "DEPGATE_TEAMS_WEBHOOK"


@dataclass
class Config:
    backend: str = "auto"
    dry_run: bool = False
    triage_confidence: float = 0.5
    auto_merge: AutoMerge = field(default_factory=AutoMerge)
    labels: Labels = field(default_factory=Labels)
    reviewers: list[str] = field(default_factory=list)
    security_reviewers: list[str] = field(default_factory=list)
    fail_check_on_hold: bool = False
    comment: bool = True
    notify: Notify = field(default_factory=Notify)
    audit_log: str = ".depgate/audit.jsonl"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        cfg = cls()
        nested: dict[str, Any] = {"auto_merge": cfg.auto_merge, "labels": cfg.labels, "notify": cfg.notify}
        for f in fields(cls):
            if f.name not in data:
                continue
            if f.name in nested:
                target = nested[f.name]
                for key, value in (data[f.name] or {}).items():
                    if hasattr(target, key):
                        setattr(target, key, value)
            else:
                setattr(cfg, f.name, data[f.name])
        cfg.auto_merge.merge_method = str(cfg.auto_merge.merge_method).upper()
        return cfg


def load_config(path: str | Path | None = None, text: str | None = None) -> Config:
    """Loads the policy from a file or from YAML text; a missing file gives the defaults."""
    if text is None:
        p = Path(path or DEFAULT_CONFIG_PATH)
        if not p.exists():
            return Config()
        text = p.read_text(encoding="utf-8")
    return Config.from_dict(yaml.safe_load(text) or {})
