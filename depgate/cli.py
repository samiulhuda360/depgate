"""Command line: `depgate check`, `depgate action`, `depgate serve`, `depgate eval`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .backends import BackendError, get_backend
from .config import load_config
from .gate import NotAnUpdate, enrich, run_gate, update_from_pr
from .github import GitHub
from .models import Update
from .sources import Fetcher
from .usage import find_usage


def cmd_check(args: argparse.Namespace) -> int:
    """Judge one update described in a JSON file (no GitHub needed)."""
    data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    update = Update.from_dict(data)
    files: dict[str, str] | Path | None = data.get("repo_files") or (Path(args.repo_dir) if args.repo_dir else None)
    if args.fetch:
        enrich(update, Fetcher(cache_dir=Path(".depgate/cache")), files)
    elif files is not None and not update.usage:
        update.usage = find_usage(update.package, update.ecosystem, update.release_notes, files)
    cfg = load_config(args.config)
    if args.no_audit:
        cfg.audit_log = ""
    result = run_gate(update, cfg, get_backend(args.backend or cfg.backend, cache_dir=Path(args.cache) if args.cache else None), dry_run=True)
    if args.json:
        print(
            json.dumps(
                {"action": result.outcome.action, "labels": result.outcome.labels, "reasons": result.outcome.reasons, "decision": result.decision.to_dict()},
                indent=1,
            )
        )
    else:
        print(result.comment)
    if args.out:
        Path(args.out).write_text(result.comment, encoding="utf-8")
    return 0


def _event_pr() -> tuple[str, int]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise SystemExit("GITHUB_EVENT_PATH is not set: run this inside GitHub Actions or pass --repo and --pr")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    if not pr and event.get("workflow_run"):
        prs = event["workflow_run"].get("pull_requests") or []
        pr = prs[0] if prs else {}
    if not pr:
        raise SystemExit("this event has no pull request")
    return repo, int(pr["number"])


def cmd_action(args: argparse.Namespace) -> int:
    """GitHub Actions entry point: judge the triggering pull request and act on it."""
    repo, number = (args.repo, args.pr) if args.repo and args.pr else _event_pr()
    cfg = load_config(args.config)
    cfg.backend = os.environ.get("DEPGATE_BACKEND") or cfg.backend
    dry = args.dry_run or cfg.dry_run
    gh = GitHub()
    checkout = Path(os.environ.get("GITHUB_WORKSPACE", ".")) if not args.remote_usage else None
    try:
        update = update_from_pr(gh, repo, number, Fetcher(cache_dir=Path(args.cache)), checkout)
    except NotAnUpdate as exc:
        print(f"depgate: skipped. {exc}")
        return 0
    try:
        result = run_gate(update, cfg, get_backend(cfg.backend), github=gh, dry_run=dry)
    except BackendError as exc:
        print(f"depgate: no decision ({exc}). Leaving the pull request for a person.")
        return 0
    print(result.comment)
    print(f"depgate actions ({'dry run, none taken' if dry else len(result.actions)}):")
    for line in result.actions:
        print(f"- {line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(result.comment + "\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"action={result.outcome.action}\nrisk={result.decision.risk}\n")
    return 1 if result.outcome.check_conclusion == "failure" else 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    serve(args.host, args.port)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from .evaluate import evaluate, write_results

    res = evaluate([b.strip() for b in args.backends.split(",") if b.strip()], progress=True)
    path = write_results(res)
    groups = [(f"all {res['n']} updates", res["backends"])]
    if res.get("subset"):
        groups.append((f"the {res['subset']['n']} updates every backend answered", res["subset"]["backends"]))
    for label, backends in groups:
        print(f"On {label}:")
        for name, r in backends.items():
            d = r["policy_default"]
            print(
                f"  {name:6s} decision acc {r['decision_accuracy']:.3f}  breaking recall {r['nouls']['breaking_in_notes']['recall']:.3f}  "
                f"safe auto-merge {d['safe']}/{r['n']}  wrong {d['wrong']} (should hold {d['wrong_hold']})  "
                f"p50 {r['latency_p50_ms']:.0f} ms  ${r['cost_per_1000_usd']:.4f}/1k"
            )
    if res["skipped"]:
        print("skipped (no cache, no key):", ", ".join(res["skipped"]))
    try:
        shown = path.relative_to(Path.cwd())
    except ValueError:
        shown = path
    print(f"wrote {shown.as_posix()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="depgate", description="Auto-merge gate for Dependabot and Renovate pull requests.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="judge one update from a JSON file (always a dry run)")
    c.add_argument("fixture")
    c.add_argument("--backend", choices=["auto", "jev", "llm", "rules"])
    c.add_argument("--config", default=None, help="policy file (default .github/depgate.yml)")
    c.add_argument("--repo-dir", help="scan this checkout for usage of the package")
    c.add_argument("--fetch", action="store_true", help="fetch missing release notes and advisories")
    c.add_argument("--cache", help="replay/record model responses in this folder")
    c.add_argument("--json", action="store_true")
    c.add_argument("--out", help="also write the comment Markdown here")
    c.add_argument("--no-audit", action="store_true")
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("action", help="GitHub Actions entry point")
    a.add_argument("--config", default=None)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--repo")
    a.add_argument("--pr", type=int)
    a.add_argument("--cache", default=".depgate/cache")
    a.add_argument("--remote-usage", action="store_true", help="use code search instead of the checkout")
    a.set_defaults(func=cmd_action)

    s = sub.add_parser("serve", help="run the webhook service")
    s.add_argument("--host", default="0.0.0.0")  # noqa: S104
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    s.set_defaults(func=cmd_serve)

    e = sub.add_parser("eval", help="evaluate the backends on the labelled set")
    e.add_argument("--backends", default="rules,jev,llm")
    e.set_defaults(func=cmd_eval)

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
