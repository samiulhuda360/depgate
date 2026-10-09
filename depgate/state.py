"""Builds the redacted state sent to a model for one update, with a release-notes digest that keeps the lines that matter."""

from __future__ import annotations

import re
from typing import Any

from .models import Update
from .redact import redact

KEY_LINE = re.compile(
    r"(?i)(breaking|backwards?[- ]incompatib|incompatible|no longer|removed?|drop(?:ped|s)?\b|rename[ds]?|deprecat|migrat|default|"
    r"security|vulnerab|cve-|ghsa-|redos|pollution|smuggl|travers|xss|injection|node(?:\.js)?\s*v?\d|python\s*3|engines?|requires?|minimum|support for)"
)


def digest_notes(notes: str, max_chars: int = 5000) -> str:
    """Keeps short notes whole. Long notes keep their headings and every line that mentions breaking changes, security
    or runtimes, then fill the remaining room from the top."""
    if len(notes) <= max_chars:
        return notes
    lines = notes.splitlines()
    keep = {i for i, line in enumerate(lines) if line.startswith("#") or KEY_LINE.search(line)}
    used = sum(len(lines[i]) + 1 for i in keep)
    for i, line in enumerate(lines):
        if i not in keep and used + len(line) + 1 <= max_chars:
            keep.add(i)
            used += len(line) + 1
    out, size = [], 0
    for i in sorted(keep):
        if size + len(lines[i]) + 1 > max_chars:
            break
        out.append(lines[i])
        size += len(lines[i]) + 1
    return "\n".join(out) + "\n... (release notes trimmed to the key lines)"


def prepare_state(update: Update, max_notes: int = 5000) -> tuple[dict[str, Any], int]:
    notes, n1 = redact(digest_notes(update.release_notes, max_notes))
    usage_text, n2 = redact("\n".join(update.usage))
    state: dict[str, Any] = {
        "package": update.package,
        "ecosystem": update.ecosystem,
        "from_version": update.from_version,
        "to_version": update.to_version,
        "semver_jump": update.jump,
        "ci_status": update.ci_status,
        "advisories": [f"{a.get('ghsa_id', '')} ({a.get('severity', '')}): {a.get('summary', '')}" for a in update.advisories] or "none listed",
        "release_notes": notes or "(no release notes found)",
        "usage": usage_text.splitlines() or ["(no usage of the package found in this repository)"],
    }
    return state, n1 + n2
