"""Turns a typed decision into actions: auto-merge or not, labels, reviewers, a check result and a notification."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .models import Decision, Update

ROUTING_ANSWERS = ("decision", "risk", "breaking_affects_repo")


@dataclass
class Outcome:
    action: str = "merge_after_review"  # auto_merge | merge_after_review | hold
    labels: list[str] = field(default_factory=list)
    user_reviewers: list[str] = field(default_factory=list)
    team_reviewers: list[str] = field(default_factory=list)
    approve: bool = False
    enable_auto_merge: bool = False
    needs_human: bool = False
    security: bool = False
    check_conclusion: str = "success"  # success | failure
    check_summary: str = ""
    notify: bool = False
    reasons: list[str] = field(default_factory=list)


def is_confident(decision: Decision, triage_confidence: float) -> bool:
    return all(decision.answers[name].confidence >= triage_confidence for name in ROUTING_ANSWERS)


def auto_merge_blockers(update: Update, decision: Decision, cfg: Config) -> list[str]:
    """Every reason the update may not be merged automatically. An empty list means it may."""
    am = cfg.auto_merge
    blockers = []
    if not am.enabled:
        blockers.append("auto-merge is turned off for this repository")
    if decision.decision != "auto_merge":
        blockers.append(f"the decision was {decision.decision.replace('_', ' ')}")
    elif decision.answers["decision"].confidence < am.min_confidence:
        blockers.append(f"decision confidence {decision.answers['decision'].confidence:.2f} is below {am.min_confidence:.2f}")
    if decision.risk > am.max_risk:
        blockers.append(f"upgrade risk {decision.risk} is above {am.max_risk}")
    if am.require_ci and update.ci_status != "success":
        blockers.append(f"CI is {update.ci_status}, not green")
    if update.jump == "major" and not am.allow_major:
        blockers.append("major version bumps are not auto-merged here")
    if decision.flag("breaking_affects_repo"):
        blockers.append("a breaking change may affect code in this repository")
    if update.package in am.ignore:
        blockers.append(f"{update.package} is on the ignore list")
    return blockers


def _add_reviewers(out: Outcome, handles: list[str]) -> None:
    for handle in handles:
        h = handle.lstrip("@")
        if "/" in h:
            team = h.split("/", 1)[1]
            if team not in out.team_reviewers:
                out.team_reviewers.append(team)
        elif h and h not in out.user_reviewers:
            out.user_reviewers.append(h)


def apply_policy(update: Update, decision: Decision, cfg: Config) -> Outcome:
    out = Outcome()
    lab = cfg.labels
    blockers = auto_merge_blockers(update, decision, cfg)
    out.needs_human = not is_confident(decision, cfg.triage_confidence)
    out.security = bool(update.advisories) or decision.flag("security_fix")
    if not blockers and not out.needs_human:
        out.action = "auto_merge"
        out.approve = cfg.auto_merge.approve
        out.enable_auto_merge = True
    else:
        hold = decision.decision == "hold" or update.ci_status == "failure" or decision.flag("breaking_affects_repo")
        out.action = "hold" if hold else "merge_after_review"
        out.reasons = blockers or ["the model was not confident enough to decide alone"]

    out.labels.append({"auto_merge": lab.auto_merge, "merge_after_review": lab.review, "hold": lab.hold}[out.action])
    if out.needs_human:
        out.labels.append(lab.needs_human)
    if out.security:
        out.labels += [lab.security, lab.priority]
    if decision.flag("breaking_in_notes"):
        out.labels.append(lab.breaking)
    if decision.flag("runtime_change"):
        out.labels.append(lab.runtime)

    if out.action != "auto_merge":
        _add_reviewers(out, cfg.reviewers)
        if out.security:
            _add_reviewers(out, cfg.security_reviewers)
    if update.author:
        out.user_reviewers = [u for u in out.user_reviewers if u.lower() != update.author.lower()]

    if out.action == "hold" and cfg.fail_check_on_hold:
        out.check_conclusion = "failure"
    verb = {"auto_merge": "Auto-merge enabled", "merge_after_review": "Needs a review", "hold": "Held"}[out.action]
    out.check_summary = f"{verb}: {update.package} {update.from_version} -> {update.to_version}, risk {decision.risk}/3."
    out.notify = ("hold" in cfg.notify.events and out.action == "hold") or ("security" in cfg.notify.events and out.security) or ("all" in cfg.notify.events)
    return out
