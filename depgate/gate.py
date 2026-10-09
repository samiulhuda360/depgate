"""One gate run: gather the inputs, decide, apply the policy, act on GitHub (unless dry run), notify and audit."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from .audit import audit_record, write_audit
from .backends import Backend
from .comment import render_comment
from .config import Config
from .github import GitHub
from .models import Decision, Update
from .notify import send_notifications
from .parse_pr import parse_bump
from .policy import Outcome, apply_policy
from .sources import Fetcher, fixed_advisories, format_notes, list_advisories, list_releases, notes_between, resolve_repo
from .usage import find_usage, import_names
from .versions import parse_version


class NotAnUpdate(ValueError):
    """The pull request is not a single-package Dependabot or Renovate update."""


@dataclass
class GateResult:
    update: Update
    decision: Decision
    outcome: Outcome
    comment: str
    actions: list[str] = field(default_factory=list)
    notified: list[str] = field(default_factory=list)


def enrich(update: Update, fetcher: Fetcher, files: dict[str, str] | Path | None = None) -> Update:
    """Fills in release notes, advisories and usage for an update that only has a package and versions."""
    old, new = parse_version(update.from_version), parse_version(update.to_version)
    if old and new and not update.release_notes:
        source = resolve_repo(fetcher, update.ecosystem, update.package)
        if source:
            between = notes_between(list_releases(fetcher, source, update.package), old, new)
            update.release_notes = format_notes(between)
            update.release_urls = [r.url for r in between][:10]
    if old and new and not update.advisories:
        fixed = fixed_advisories(list_advisories(fetcher, update.ecosystem, update.package), old, new)
        update.advisories = [{"ghsa_id": a.ghsa_id, "summary": a.summary, "severity": a.severity, "url": a.url} for a in fixed]
    if files is not None and not update.usage:
        update.usage = find_usage(update.package, update.ecosystem, update.release_notes, files)
    return update


def remote_usage_files(gh: GitHub, repo: str, package: str, ecosystem: str, limit: int = 6) -> dict[str, str]:
    """For the webhook service (no checkout): code search for files that import the package, then fetch them."""
    term = import_names(package, ecosystem)[0]
    found: dict[str, str] = {}
    for manifest in ("package.json", "pyproject.toml"):
        text = gh.fetch_config_text(repo, path=manifest)
        if text:
            found[manifest] = text
    try:
        hits = gh._req("GET", "/search/code", params={"q": f'"{term}" repo:{repo}', "per_page": limit}).get("items", [])
    except Exception:  # noqa: BLE001 - code search is optional (rate limits, unindexed repos)
        hits = []
    for item in hits[:limit]:
        blob = gh._req("GET", f"/repos/{repo}/contents/{item['path']}")
        if blob and blob.get("encoding") == "base64":
            found[item["path"]] = base64.b64decode(blob["content"]).decode("utf-8", errors="replace")
    return found


def update_from_pr(gh: GitHub, repo: str, number: int, fetcher: Fetcher, checkout: Path | None = None) -> Update:
    """Builds a full Update from a live pull request."""
    pr = gh.get_pr(repo, number)
    files = gh.pr_files(repo, number)
    bump = parse_bump(pr["title"], pr.get("body") or "", (pr.get("head") or {}).get("ref", ""), files)
    if bump is None:
        raise NotAnUpdate(f"#{number} is not a single-package dependency update: {pr['title']!r}")
    sha = (pr.get("head") or {}).get("sha", "")
    update = Update(
        package=bump.package,
        ecosystem=bump.ecosystem,
        from_version=bump.from_version,
        to_version=bump.to_version,
        jump=bump.jump,
        ci_status=gh.ci_status(repo, sha) if sha else "unknown",
        title=pr["title"],
        repo=repo,
        number=number,
        url=pr.get("html_url", ""),
        head_sha=sha,
        node_id=pr.get("node_id", ""),
        author=(pr.get("user") or {}).get("login", ""),
    )
    source = checkout if checkout is not None else remote_usage_files(gh, repo, bump.package, bump.ecosystem)
    return enrich(update, fetcher, source)


def run_gate(update: Update, cfg: Config, backend: Backend, github: GitHub | None = None, dry_run: bool | None = None, audit: bool = True) -> GateResult:
    dry = cfg.dry_run if dry_run is None else dry_run
    decision = backend.decide(update)
    outcome = apply_policy(update, decision, cfg)
    comment = render_comment(update, decision, outcome, dry_run=dry or github is None)
    result = GateResult(update, decision, outcome, comment)
    if github is not None and not dry and update.number:
        result.actions = github.apply(update.repo, update.number, update.head_sha, update.node_id, outcome, comment, cfg)
    result.notified = send_notifications(update, decision, outcome, cfg, dry_run=dry)
    if audit and cfg.audit_log:
        write_audit(cfg.audit_log, audit_record(update, decision, outcome, dry_run=dry or github is None))
    return result
