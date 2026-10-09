"""End-to-end demo of the GitHub Action code path against a local stand-in for the GitHub API.

It serves one Dependabot pull request (from a fixture), forwards the public release-notes and advisory lookups to
the real GitHub API, runs `depgate action` exactly as the Action does, and prints every write depgate made
(labels, comment, approval, auto-merge, status). Nothing on github.com is changed.

    python scripts/demo_github.py fixtures/security-fix.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
SHA = "4f1c2e9d8b7a6c5d4e3f2a1b0c9d8e7f6a5b4c3d"


def make_handler(fx: dict[str, Any], writes: list[dict[str, Any]]) -> type[BaseHTTPRequestHandler]:
    repo, number = fx["repo"], fx["number"]
    manifest = "package.json" if fx["ecosystem"] == "npm" else "requirements.txt"
    lock = "package-lock.json" if fx["ecosystem"] == "npm" else "requirements.lock"
    branch = f"dependabot/{'npm_and_yarn' if fx['ecosystem'] == 'npm' else 'pip'}/{fx['package']}-{fx['to_version']}"
    pr = {
        "number": number,
        "title": fx["title"],
        "body": f"Bumps {fx['package']} from {fx['from_version']} to {fx['to_version']}.",
        "html_url": fx["url"],
        "node_id": "PR_kwDOdemo42",
        "user": {"login": "dependabot[bot]"},
        "head": {"sha": SHA, "ref": branch},
    }
    routes: dict[str, Any] = {
        f"/repos/{repo}/pulls/{number}": pr,
        f"/repos/{repo}/pulls/{number}/files": [{"filename": manifest}, {"filename": lock}],
        f"/repos/{repo}/commits/{SHA}/check-runs": {"check_runs": [{"name": "test", "status": "completed", "conclusion": fx["ci_status"]}]},
        f"/repos/{repo}/commits/{SHA}/status": {"statuses": []},
        f"/repos/{repo}/issues/{number}/labels": [{"name": "dependencies"}],
        f"/repos/{repo}/issues/{number}/comments": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: Any) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path in routes:
                self._send(200, routes[path])
            elif path.endswith("/releases") or path == "/advisories":
                # Public, read-only lookups go to the real GitHub API.
                real = httpx.get("https://api.github.com" + self.path, headers={"Accept": "application/vnd.github+json"}, timeout=30)
                self._send(real.status_code, real.json())
            else:
                self._send(404, {"message": "Not Found"})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            writes.append({"method": "POST", "path": self.path, "body": body})
            self._send(200, {})

        def do_PATCH(self) -> None:
            self.do_POST()

        def do_DELETE(self) -> None:
            writes.append({"method": "DELETE", "path": self.path, "body": None})
            self._send(204, {})

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    fixture = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "fixtures" / "security-fix.json")
    fx = json.loads(fixture.read_text(encoding="utf-8"))
    writes: list[dict[str, Any]] = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fx, writes))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{httpd.server_address[1]}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for rel, text in fx["repo_files"].items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text, encoding="utf-8")
        event = work / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": fx["number"]}}), encoding="utf-8")
        env = {
            **os.environ,
            "GITHUB_API_URL": api,
            "GITHUB_GRAPHQL_URL": f"{api}/graphql",
            "GITHUB_TOKEN": "demo-token-not-real",
            "GITHUB_REPOSITORY": fx["repo"],
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_WORKSPACE": str(work),
            "PYTHONIOENCODING": "utf-8",
        }
        cmd = [sys.executable, "-m", "depgate", "action", "--config", str(ROOT / "examples" / "depgate.yml"), "--cache", str(work / ".cache")]
        proc = subprocess.run(cmd, env=env, cwd=work, capture_output=True, text=True, encoding="utf-8", check=False)
    httpd.shutdown()
    head = next((line for line in proc.stdout.splitlines() if line.startswith("`")), "")
    print(f"$ depgate action   # PR #{fx['number']} in {fx['repo']}: {fx['title']}")
    print(f"  {head}")
    print("  depgate log:")
    log = proc.stdout.split("depgate actions", 1)[-1].splitlines()[1:]
    for line in log:
        print(f"    {line}")
    print(f"depgate exited with code {proc.returncode}; {len(writes)} writes to the pull request:")
    for w in writes:
        body = w["body"] or {}
        detail = body.get("labels") or body.get("event") or body.get("state") or (body.get("variables") or {}).get("method") or ""
        if "body" in body and not detail:
            detail = f"comment, {len(body['body'])} characters"
        print(f"  {w['method']:6s} {w['path']}  {detail}")
    comment = next((w["body"]["body"] for w in writes if w["path"].endswith("/comments")), "")
    if comment:
        out = ROOT / "docs" / "build" / "demo-comment.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(comment, encoding="utf-8", newline="\n")
        print(f"posted comment saved to {out.relative_to(ROOT).as_posix()}")
    if proc.returncode not in (0, 1):
        print(proc.stderr[-2000:])
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
