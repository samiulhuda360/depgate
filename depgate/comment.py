"""The one summary comment posted on each update pull request, quoting the release-note lines that matter."""

from __future__ import annotations

import re

from .models import Decision, Update
from .policy import Outcome
from .state import KEY_LINE
from .usage import symbols_from_notes

MARKER = "<!-- depgate -->"
ACTION_TITLES = {"auto_merge": "auto-merge enabled", "merge_after_review": "needs a review", "hold": "hold: do not merge yet"}
NOUL_LABELS = {
    "breaking_in_notes": "Release notes describe a breaking change",
    "breaking_affects_repo": "A breaking change affects APIs this repo uses",
    "security_fix": "Fixes a security vulnerability",
    "runtime_change": "Changes runtime or engine requirements",
}


CODE_LIKE = re.compile(r"^(?:const|let|var|import|from|def|class|return|await)\s|[;{(,]$|^[{}()\[\]]|=>\s*\{|^\w+\.\w+\(.*\)$")


def relevant_lines(update: Update, limit: int = 8) -> list[str]:
    """Release-note lines about breaking changes, security or runtimes, or that name a symbol the repo uses."""
    used = " ".join(update.usage)
    symbols = [s for s in symbols_from_notes(update.release_notes, update.package) if re.search(rf"(?<![\w$]){re.escape(s)}(?![\w$])", used)]
    sym_re = re.compile("|".join(rf"(?<![\w$]){re.escape(s)}(?![\w$])" for s in symbols)) if symbols else None
    picked: list[str] = []
    in_code = False
    for raw in update.release_notes.splitlines():
        if raw.strip().startswith("```"):
            in_code = not in_code
            continue
        line = raw.strip().lstrip("-*• ").strip()
        if in_code or len(line) < 12 or line.startswith(("#", "http", "**Full Changelog", "Full Changelog")) or CODE_LIKE.search(line):
            continue
        if KEY_LINE.search(line) or (sym_re and sym_re.search(line)):
            line = re.sub(r"\s+", " ", line)
            picked.append(line if len(line) <= 220 else line[:217] + "...")
        if len(picked) >= limit:
            break
    return picked


def render_comment(update: Update, decision: Decision, outcome: Outcome, dry_run: bool = False) -> str:
    title = ACTION_TITLES[outcome.action]
    lines = [
        MARKER,
        f"### depgate: **{title}**",
        "",
        f"`{update.package}` {update.from_version} → {update.to_version} ({update.jump or 'unknown'} bump, {update.ecosystem}) · CI: {update.ci_status} · upgrade risk {decision.risk}/3",
        "",
        "| Question | Answer | Confidence |",
        "|---|---|---|",
        f"| Decision | {decision.decision.replace('_', ' ')} | {decision.answers['decision'].confidence:.2f} |",
        f"| Upgrade risk | {decision.risk} of 3 | {decision.answers['risk'].confidence:.2f} |",
    ]
    for name, label in NOUL_LABELS.items():
        ans = decision.answers[name]
        p = float(ans.value)
        lines.append(f"| {label} | {'yes' if p >= 0.5 else 'no'} (p={p:.2f}) | {ans.confidence:.2f} |")
    lines.append("")
    if outcome.reasons:
        lines.append("**Why it was not auto-merged**")
        lines += [f"- {r}" for r in outcome.reasons]
        lines.append("")
    if update.advisories:
        lines.append("**Security advisories fixed**")
        lines += [f"- [{a.get('ghsa_id', 'advisory')}]({a.get('url', '')}) ({a.get('severity', 'unknown')}): {a.get('summary', '')}" for a in update.advisories]
        lines.append("")
    quotes = relevant_lines(update)
    if quotes:
        lines.append("**Relevant release-note lines**")
        lines += [f"> {q}" for q in quotes]
        lines.append("")
    if update.usage:
        lines.append("<details><summary>How this repository uses the package</summary>\n")
        lines.append("```")
        lines += update.usage[:15]
        lines.append("```\n</details>\n")
    actions = [f"labels {', '.join(f'`{label}`' for label in outcome.labels)}"]
    reviewers = [f"@{u}" for u in outcome.user_reviewers] + [f"team `{t}`" for t in outcome.team_reviewers]
    if reviewers:
        actions.append("review requested from " + ", ".join(reviewers))
    if outcome.enable_auto_merge:
        actions.append("approved and set to merge when checks pass" if outcome.approve else "set to merge when checks pass")
    lines.append("**Actions:** " + " · ".join(actions))
    lines.append("")
    foot = f"Decided by {decision.model} in {decision.latency_ms:.0f} ms."
    if decision.redactions:
        foot += f" {decision.redactions} likely secret(s) redacted before sending."
    if dry_run:
        foot += " Dry run: nothing on the pull request was changed."
    lines.append(f"<sub>{foot}</sub>")
    return "\n".join(lines) + "\n"
