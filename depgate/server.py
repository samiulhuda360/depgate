"""Self-hosted webhook service: GitHub sends pull_request and check_suite events, depgate judges each update PR.

Standard library only. Signatures are checked with DEPGATE_WEBHOOK_SECRET; work runs on a background thread so
GitHub gets a quick 202.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .backends import get_backend
from .config import load_config
from .gate import NotAnUpdate, run_gate, update_from_pr
from .github import GitHub
from .sources import Fetcher

log = logging.getLogger("depgate.server")
BOT_AUTHORS = {"dependabot[bot]", "renovate[bot]", "dependabot-preview[bot]"}


def verify_signature(secret: str, body: bytes, header: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def targets(event: str, payload: dict[str, Any]) -> list[tuple[str, int]]:
    """(repo, PR number) pairs this event asks us to judge."""
    repo = (payload.get("repository") or {}).get("full_name", "")
    if event == "pull_request" and payload.get("action") in ("opened", "reopened", "synchronize", "edited"):
        pr = payload.get("pull_request") or {}
        if (pr.get("user") or {}).get("login") in BOT_AUTHORS:
            return [(repo, int(pr["number"]))]
    if event == "check_suite" and payload.get("action") == "completed":
        return [(repo, int(p["number"])) for p in (payload.get("check_suite") or {}).get("pull_requests", [])]
    return []


def handle(repo: str, number: int) -> None:
    gh = GitHub()
    text = gh.fetch_config_text(repo)
    cfg = load_config(text=text) if text is not None else load_config(os.environ.get("DEPGATE_CONFIG"))
    if os.environ.get("DEPGATE_AUDIT_LOG"):
        cfg.audit_log = os.environ["DEPGATE_AUDIT_LOG"]
    dry = cfg.dry_run or os.environ.get("DEPGATE_DRY_RUN", "") not in ("", "0", "false")
    try:
        update = update_from_pr(gh, repo, number, Fetcher(cache_dir=Path(os.environ.get("DEPGATE_CACHE_DIR", ".depgate/cache"))))
    except NotAnUpdate as exc:
        log.info("skipped: %s", exc)
        return
    result = run_gate(update, cfg, get_backend(cfg.backend), github=gh, dry_run=dry)
    log.info("%s#%s %s %s->%s: %s %s", repo, number, update.package, update.from_version, update.to_version, result.outcome.action, result.actions)


class Handler(BaseHTTPRequestHandler):
    server_version = "depgate"

    def _reply(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/webhook":
            self._reply(404, {"error": "not found"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        secret = os.environ.get("DEPGATE_WEBHOOK_SECRET", "")
        if not secret or not verify_signature(secret, body, self.headers.get("X-Hub-Signature-256", "")):
            self._reply(401, {"error": "bad or missing signature"})
            return
        event = self.headers.get("X-GitHub-Event", "")
        jobs = targets(event, json.loads(body or b"{}"))
        for repo, number in jobs:
            threading.Thread(target=self._safe_handle, args=(repo, number), daemon=True).start()
        self._reply(202, {"queued": [f"{r}#{n}" for r, n in jobs]})

    @staticmethod
    def _safe_handle(repo: str, number: int) -> None:
        try:
            handle(repo, number)
        except Exception:
            log.exception("failed to judge %s#%s", repo, number)

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), fmt % args)


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:  # noqa: S104 - a container listens on all interfaces
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.environ.get("DEPGATE_WEBHOOK_SECRET"):
        raise SystemExit("DEPGATE_WEBHOOK_SECRET must be set: unsigned webhooks are rejected")
    httpd = ThreadingHTTPServer((host, port), Handler)
    log.info("depgate listening on %s:%s", host, port)
    httpd.serve_forever()
