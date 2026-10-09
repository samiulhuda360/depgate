"""Chat notifications for held updates and security fixes (Slack or Teams incoming webhooks)."""

from __future__ import annotations

import os

import httpx

from .config import Config
from .models import Decision, Update
from .policy import Outcome


def notification_text(update: Update, decision: Decision, outcome: Outcome) -> str:
    where = f"{update.repo}#{update.number}" if update.number else (update.repo or "a repository")
    what = f"{update.package} {update.from_version} -> {update.to_version}"
    head = "Security update" if outcome.security else "Dependency update"
    status = {"auto_merge": "set to auto-merge", "merge_after_review": "needs a review", "hold": "held"}[outcome.action]
    why = f" Why: {'; '.join(outcome.reasons)}." if outcome.reasons else ""
    return f"{head} in {where}: {what} is {status} (risk {decision.risk}/3).{why} {update.url}".strip()


def send_notifications(update: Update, decision: Decision, outcome: Outcome, cfg: Config, dry_run: bool = False) -> list[str]:
    """Posts to every configured webhook. Returns the channels notified (or that would be, in a dry run)."""
    if not outcome.notify:
        return []
    text = notification_text(update, decision, outcome)
    sent: list[str] = []
    for channel, env in (("slack", cfg.notify.slack_webhook_env), ("teams", cfg.notify.teams_webhook_env)):
        url = os.environ.get(env, "")
        if not url:
            continue
        if not dry_run:
            httpx.post(url, json={"text": text}, timeout=10).raise_for_status()
        sent.append(channel)
    return sent
