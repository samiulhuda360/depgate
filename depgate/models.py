"""Core data types: a dependency update going in, a typed decision coming out."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Update:
    """One dependency-update pull request, with everything the gate needs to judge it."""

    package: str
    ecosystem: str  # "npm" | "pip"
    from_version: str
    to_version: str
    jump: str = ""  # "major" | "minor" | "patch"
    release_notes: str = ""
    advisories: list[dict[str, str]] = field(default_factory=list)
    ci_status: str = "unknown"  # "success" | "failure" | "pending" | "unknown"
    usage: list[str] = field(default_factory=list)
    # Pull request context (empty for offline fixtures)
    title: str = ""
    repo: str = ""
    number: int | None = None
    url: str = ""
    head_sha: str = ""
    node_id: str = ""
    author: str = ""
    release_urls: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Update:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Answer:
    """One typed answer. `value` is the chosen option (str), level (int) or probability of yes (float)."""

    kind: str  # "choice" | "score" | "noul"
    value: Any
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)

    @property
    def flag(self) -> bool:
        """A Noul as a yes/no decision at p >= 0.5."""
        return bool(self.kind == "noul" and float(self.value) >= 0.5)


@dataclass
class Decision:
    backend: str
    model: str
    answers: dict[str, Answer]
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    redactions: int = 0

    @property
    def decision(self) -> str:
        return str(self.answers["decision"].value)

    @property
    def risk(self) -> int:
        return int(self.answers["risk"].value)

    def flag(self, name: str) -> bool:
        return self.answers[name].flag

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
