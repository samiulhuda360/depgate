"""A minimal GitHub client: read an update PR and its CI state, then label, comment, request review, approve and
enable auto-merge."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .comment import MARKER
from .config import Config
from .policy import Outcome

STATUS_CONTEXT = "depgate"
FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "error"}
PASSED = {"success", "neutral", "skipped"}

ENABLE_AUTO_MERGE = """mutation($id: ID!, $method: PullRequestMergeMethod!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $method}) { clientMutationId }
}"""


def _error_message(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", ""))
    except ValueError:
        return ""


class GitHub:
    def __init__(self, token: str | None = None, api_url: str | None = None, client: httpx.Client | None = None) -> None:
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.graphql_url = os.environ.get("GITHUB_GRAPHQL_URL") or f"{self.api_url}/graphql"
        token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "depgate"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.http = client or httpx.Client(timeout=30)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        resp = self.http.request(method, f"{self.api_url}{path}", headers=self.headers, **kw)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def get_pr(self, repo: str, number: int) -> dict[str, Any]:
        return dict(self._req("GET", f"/repos/{repo}/pulls/{number}"))

    def pr_files(self, repo: str, number: int) -> list[str]:
        return [f["filename"] for f in self._req("GET", f"/repos/{repo}/pulls/{number}/files", params={"per_page": 100})]

    def ci_status(self, repo: str, sha: str, ignore: tuple[str, ...] = (STATUS_CONTEXT,)) -> str:
        """`success`, `failure`, `pending` or `unknown`, from check runs and commit statuses (ignoring depgate's own)."""
        states: list[str] = []
        runs = self._req("GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100}).get("check_runs", [])
        for run in runs:
            if run.get("name") in ignore:
                continue
            states.append("pending" if run.get("status") != "completed" else (run.get("conclusion") or "pending"))
        combined = self._req("GET", f"/repos/{repo}/commits/{sha}/status")
        for status in combined.get("statuses", []):
            if status.get("context") not in ignore:
                states.append(status.get("state", "pending"))
        if not states:
            return "unknown"
        if any(s in FAILED for s in states):
            return "failure"
        if all(s in PASSED for s in states):
            return "success"
        return "pending"

    def fetch_config_text(self, repo: str, ref: str = "", path: str = ".github/depgate.yml") -> str | None:
        """Reads the repository's policy file (default branch unless `ref`). None when there is none."""
        resp = self.http.get(
            f"{self.api_url}/repos/{repo}/contents/{path}",
            headers={**self.headers, "Accept": "application/vnd.github.raw+json"},
            params={"ref": ref} if ref else None,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def managed_labels(self, cfg: Config) -> set[str]:
        lab = cfg.labels
        return {lab.auto_merge, lab.review, lab.hold, lab.needs_human, lab.security, lab.priority, lab.breaking, lab.runtime}

    def apply(self, repo: str, number: int, head_sha: str, node_id: str, outcome: Outcome, comment: str, cfg: Config) -> list[str]:
        """Applies the outcome to the pull request. Returns a log of what was done."""
        done: list[str] = []
        current = {label["name"] for label in self._req("GET", f"/repos/{repo}/issues/{number}/labels")}
        for stale in sorted((current & self.managed_labels(cfg)) - set(outcome.labels)):
            self._req("DELETE", f"/repos/{repo}/issues/{number}/labels/{stale}")
            done.append(f"removed label {stale}")
        new = [label for label in outcome.labels if label not in current]
        if new:
            self._req("POST", f"/repos/{repo}/issues/{number}/labels", json={"labels": new})
            done.append(f"added labels {', '.join(new)}")
        if cfg.comment:
            existing = [c for c in self._req("GET", f"/repos/{repo}/issues/{number}/comments", params={"per_page": 100}) if MARKER in (c.get("body") or "")]
            if existing:
                self._req("PATCH", f"/repos/{repo}/issues/comments/{existing[0]['id']}", json={"body": comment})
                done.append("updated the summary comment")
            else:
                self._req("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": comment})
                done.append("posted the summary comment")
        if outcome.user_reviewers or outcome.team_reviewers:
            self._req(
                "POST",
                f"/repos/{repo}/pulls/{number}/requested_reviewers",
                json={"reviewers": outcome.user_reviewers, "team_reviewers": outcome.team_reviewers},
            )
            done.append("requested review from " + ", ".join(outcome.user_reviewers + outcome.team_reviewers))
        if outcome.approve:
            try:
                self._req("POST", f"/repos/{repo}/pulls/{number}/reviews", json={"event": "APPROVE", "body": "Approved by depgate: low-risk update, CI green."})
                done.append("approved the pull request")
            except httpx.HTTPStatusError as exc:
                # GitHub refuses approvals from Actions unless "Allow GitHub Actions to create and approve pull
                # requests" is on in the repository's Actions settings. Carry on: auto-merge and the status still apply.
                reason = _error_message(exc.response) or f"HTTP {exc.response.status_code}"
                done.append(f"could not approve: {reason}")
        if outcome.enable_auto_merge and node_id:
            resp = self.http.post(
                self.graphql_url, headers=self.headers, json={"query": ENABLE_AUTO_MERGE, "variables": {"id": node_id, "method": cfg.auto_merge.merge_method}}
            )
            resp.raise_for_status()
            errors = resp.json().get("errors")
            done.append(
                "could not enable auto-merge: " + errors[0].get("message", "") if errors else f"enabled auto-merge ({cfg.auto_merge.merge_method.lower()})"
            )
        if head_sha:
            state = "failure" if outcome.check_conclusion == "failure" else "success"
            self._req(
                "POST", f"/repos/{repo}/statuses/{head_sha}", json={"state": state, "context": STATUS_CONTEXT, "description": outcome.check_summary[:140]}
            )
            done.append(f"set status {STATUS_CONTEXT}={state}")
        return done
