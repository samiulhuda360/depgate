"""The six typed questions asked about every dependency update, in one call.

The same definitions drive the Jev request, the LLM prompt and the evaluation.
"""

from __future__ import annotations

from typing import Any

DECISIONS: dict[str, str] = {
    "auto_merge": "safe to merge without a person: no breaking change that touches this repository, no runtime requirement change, CI is green and the upgrade risk is low",
    "merge_after_review": "probably fine, but a person should read the release notes first: a breaking change that does not touch this repository, a runtime requirement change, a major bump with unclear notes, or CI still running",
    "hold": "do not merge yet: CI is failing, or a breaking change affects APIs, options or runtimes this repository uses",
}

RISK_LEVELS: list[str] = [
    "0 - trivial: a patch with only bug fixes, docs or internal changes; CI green",
    "1 - low: new features, behaviour fixes, deprecations or a security fix, with no breaking change; CI green",
    "2 - medium: a breaking change that does not touch this repository, a runtime requirement change, a major bump with unclear notes, or CI still running",
    "3 - high: a breaking change that touches APIs this repository uses, or CI failing",
]

NOULS: dict[str, str] = {
    "breaking_in_notes": "The release notes describe a breaking change: existing users may have to change code, configuration or environment (for example removed or renamed APIs, changed defaults, or dropped runtime versions). A major version number alone does not count.",
    "breaking_affects_repo": "A breaking change described in the release notes affects APIs, options or runtime versions that this repository uses, as shown in `usage`.",
    "security_fix": "This update fixes a security vulnerability (an advisory is listed, or the notes describe a security fix).",
    "runtime_change": "This update changes runtime or engine requirements, such as raising the minimum Node or Python version or dropping support for one.",
}

QUESTION_NAMES: list[str] = ["decision", "risk", *NOULS]


def jev_questions() -> dict[str, dict[str, Any]]:
    """The `questions` map for one Jev System One request."""
    questions: dict[str, dict[str, Any]] = {
        "decision": {
            "type": "choice",
            "instructions": "Should this dependency update be merged automatically? Judge the `release_notes` against how this repository uses the package (`usage`), the `ci_status` and any `advisories`.",
            "criteria": DECISIONS,
        },
        "risk": {
            "type": "score",
            "instructions": "How risky is this upgrade for this repository?",
            "criteria": RISK_LEVELS,
        },
    }
    for name, statement in NOULS.items():
        questions[name] = {"type": "noul", "instructions": statement}
    return questions
