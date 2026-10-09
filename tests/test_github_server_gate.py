from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import FakeBackend, make_decision

from depgate.comment import MARKER
from depgate.config import Config
from depgate.gate import run_gate
from depgate.github import GitHub
from depgate.metrics import accuracy, brier, macro_f1, percentile, prf, reliability
from depgate.models import Update
from depgate.server import targets, verify_signature


class FakeGitHubAPI:
    """Records every request and answers like the GitHub REST and GraphQL APIs."""

    def __init__(self, labels: list[str] | None = None, comments: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.labels = labels or []
        self.comments = comments or []
        self.check_runs: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if path.endswith("/labels") and request.method == "GET":
            return httpx.Response(200, json=[{"name": n} for n in self.labels])
        if path.endswith("/comments") and request.method == "GET":
            return httpx.Response(200, json=self.comments)
        if path.endswith("/check-runs"):
            return httpx.Response(200, json={"check_runs": self.check_runs})
        if path.endswith("/status"):
            return httpx.Response(200, json={"statuses": self.statuses})
        if path == "/graphql":
            return httpx.Response(200, json={"data": {"enablePullRequestAutoMerge": {"clientMutationId": None}}})
        return httpx.Response(200, json={})


def client(api: FakeGitHubAPI) -> GitHub:
    return GitHub(token="test-token-not-real", api_url="https://gh.test", client=httpx.Client(transport=httpx.MockTransport(api)))


def test_apply_auto_merge(update: Update) -> None:
    api = FakeGitHubAPI(labels=["depgate:review", "dependencies"])
    gh = client(api)
    result = run_gate(update, Config(audit_log=""), FakeBackend(make_decision()), github=gh, dry_run=False)
    methods = [(m, p) for m, p, _ in api.calls]
    assert ("DELETE", "/repos/example/orders-api/issues/7/labels/depgate:review") in methods  # stale managed label
    assert not any(p.endswith("/labels/dependencies") for _, p in methods)  # unmanaged label kept
    assert ("POST", "/repos/example/orders-api/pulls/7/reviews") in methods
    graphql = next(b for m, p, b in api.calls if p == "/graphql")
    assert graphql["variables"] == {"id": "PR_node", "method": "SQUASH"}
    status = next(b for m, p, b in api.calls if p.startswith("/repos/example/orders-api/statuses/"))
    assert status["state"] == "success" and status["context"] == "depgate"
    assert "enabled auto-merge (squash)" in result.actions


def test_comment_is_updated_not_duplicated(update: Update) -> None:
    api = FakeGitHubAPI(comments=[{"id": 99, "body": MARKER + "\nold"}])
    run_gate(update, Config(audit_log=""), FakeBackend(make_decision("hold", risk=3, breaking_affects_repo=0.9)), github=client(api), dry_run=False)
    assert ("PATCH", "/repos/example/orders-api/issues/comments/99") in [(m, p) for m, p, _ in api.calls]
    assert not any(m == "POST" and p.endswith("/comments") for m, p, _ in api.calls)
    assert not any(p == "/graphql" for _, p, _ in api.calls)


def test_dry_run_changes_nothing_but_audits(update: Update, tmp_path: Path) -> None:
    api = FakeGitHubAPI()
    log = tmp_path / "audit.jsonl"
    result = run_gate(update, Config(audit_log=str(log)), FakeBackend(make_decision()), github=client(api), dry_run=True)
    assert api.calls == []
    assert "Dry run" in result.comment
    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["action"] == "auto_merge" and record["dry_run"] is True and record["package"] == "axios"


def test_notifier_posts_for_holds(update: Update, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setenv("DEPGATE_SLACK_WEBHOOK", "https://hooks.test/slack")

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> httpx.Response:
        sent.append(json)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = run_gate(update, Config(audit_log=""), FakeBackend(make_decision("hold", risk=3, breaking_affects_repo=0.9)), dry_run=False)
    assert result.notified == ["slack"] and "is held" in sent[0]["text"]


@pytest.mark.parametrize(
    ("runs", "statuses", "expected"),
    [
        ([], [], "unknown"),
        ([{"name": "test", "status": "completed", "conclusion": "success"}], [], "success"),
        ([{"name": "test", "status": "in_progress", "conclusion": None}], [], "pending"),
        ([{"name": "test", "status": "completed", "conclusion": "success"}], [{"context": "lint", "state": "failure"}], "failure"),
        ([{"name": "depgate", "status": "completed", "conclusion": "failure"}], [{"context": "ci", "state": "success"}], "success"),
    ],
)
def test_ci_status(runs: list[dict[str, Any]], statuses: list[dict[str, Any]], expected: str) -> None:
    api = FakeGitHubAPI()
    api.check_runs, api.statuses = runs, statuses
    assert client(api).ci_status("example/orders-api", "abc123") == expected


def test_webhook_signature_and_targets() -> None:
    body = b'{"action":"opened"}'
    sig = "sha256=" + hmac.new(b"test-secret-not-real", body, hashlib.sha256).hexdigest()
    assert verify_signature("test-secret-not-real", body, sig)
    assert not verify_signature("other", body, sig)
    assert not verify_signature("test-secret-not-real", body, "")
    pr_event = {"action": "opened", "repository": {"full_name": "o/r"}, "pull_request": {"number": 5, "user": {"login": "dependabot[bot]"}}}
    assert targets("pull_request", pr_event) == [("o/r", 5)]
    human = {**pr_event, "pull_request": {"number": 6, "user": {"login": "someone"}}}
    assert targets("pull_request", human) == []
    suite = {"action": "completed", "repository": {"full_name": "o/r"}, "check_suite": {"pull_requests": [{"number": 8}]}}
    assert targets("check_suite", suite) == [("o/r", 8)]


def test_metrics() -> None:
    assert accuracy([1, 2, 3], [1, 2, 0]) == pytest.approx(2 / 3)
    assert prf([True, True, False], [True, False, True]) == pytest.approx((0.5, 0.5, 0.5))
    assert macro_f1(["a", "b"], ["a", "b"], ["a", "b"]) == 1.0
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5], [True]) == 0.25
    rows = reliability([0.95, 0.92, 0.55], [True, False, True])
    assert rows[-1][1] == 2 and rows[-1][3] == 0.5
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
