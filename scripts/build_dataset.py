"""Build the evaluation set: real version bumps of popular npm and PyPI packages, with their public release notes.

For each package the script lists the GitHub releases, samples major, minor and patch bumps (plus one bump that
crosses a security fix when the GitHub Advisory Database lists one), joins the release notes between the two
versions, adds a simulated CI result and writes `eval/data/updates.jsonl`. Read-only public API calls, cached under `eval/.http-cache/`.

    GITHUB_TOKEN=... python scripts/build_dataset.py --target 200 --seed 11
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from depgate.sources import Fetcher, Release, fixed_advisories, format_notes, list_advisories, list_releases, notes_between
from depgate.versions import semver_jump

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "data" / "updates.jsonl"

PACKAGES: list[tuple[str, str, str]] = [
    ("npm", "axios", "axios/axios"),
    ("npm", "express", "expressjs/express"),
    ("npm", "vite", "vitejs/vite"),
    ("npm", "vitest", "vitest-dev/vitest"),
    ("npm", "eslint", "eslint/eslint"),
    ("npm", "commander", "tj/commander.js"),
    ("npm", "yargs", "yargs/yargs"),
    ("npm", "zod", "colinhacks/zod"),
    ("npm", "socket.io", "socketio/socket.io"),
    ("npm", "fastify", "fastify/fastify"),
    ("npm", "knex", "knex/knex"),
    ("npm", "sequelize", "sequelize/sequelize"),
    ("npm", "pino", "pinojs/pino"),
    ("npm", "winston", "winstonjs/winston"),
    ("npm", "jest", "jestjs/jest"),
    ("npm", "mocha", "mochajs/mocha"),
    ("npm", "svelte", "sveltejs/svelte"),
    ("npm", "esbuild", "evanw/esbuild"),
    ("npm", "webpack", "webpack/webpack"),
    ("npm", "undici", "nodejs/undici"),
    ("npm", "got", "sindresorhus/got"),
    ("npm", "dayjs", "iamkun/dayjs"),
    ("npm", "chart.js", "chartjs/Chart.js"),
    ("npm", "mysql2", "sidorares/node-mysql2"),
    ("npm", "chalk", "chalk/chalk"),
    ("npm", "ws", "websockets/ws"),
    ("npm", "semver", "npm/node-semver"),
    ("pip", "requests", "psf/requests"),
    ("pip", "httpx", "encode/httpx"),
    ("pip", "fastapi", "fastapi/fastapi"),
    ("pip", "pydantic", "pydantic/pydantic"),
    ("pip", "flask", "pallets/flask"),
    ("pip", "click", "pallets/click"),
    ("pip", "werkzeug", "pallets/werkzeug"),
    ("pip", "jinja2", "pallets/jinja"),
    ("pip", "sqlalchemy", "sqlalchemy/sqlalchemy"),
    ("pip", "pytest", "pytest-dev/pytest"),
    ("pip", "black", "psf/black"),
    ("pip", "uvicorn", "encode/uvicorn"),
    ("pip", "starlette", "encode/starlette"),
    ("pip", "typer", "fastapi/typer"),
    ("pip", "attrs", "python-attrs/attrs"),
    ("pip", "urllib3", "urllib3/urllib3"),
    ("pip", "jsonschema", "python-jsonschema/jsonschema"),
    ("pip", "pyjwt", "jpadilla/pyjwt"),
    ("pip", "tox", "tox-dev/tox"),
    ("pip", "poetry", "python-poetry/poetry"),
    ("pip", "rich", "Textualize/rich"),
    ("pip", "sqlmodel", "fastapi/sqlmodel"),
    ("pip", "tenacity", "jd/tenacity"),
    ("pip", "python-dotenv", "theskumar/python-dotenv"),
    ("pip", "loguru", "Delgan/loguru"),
]


def candidates(releases: list[Release], rng: random.Random) -> dict[str, list[tuple[Release, Release]]]:
    out: dict[str, list[tuple[Release, Release]]] = {"major": [], "minor": [], "patch": []}
    for i in range(1, len(releases)):
        old, new = releases[i - 1], releases[i]
        jump = semver_jump(old.version, new.version)
        if jump == "major":
            # Dependabot often skips a few releases: sometimes jump further into the new major.
            j = min(len(releases) - 1, i + rng.choice([0, 0, 1, 2]))
            if releases[j].version.major == new.version.major:
                new = releases[j]
        if jump in out:
            out[jump].append((old, new))
    return out


def item(eco: str, pkg: str, repo: str, old: Release, new: Release, releases: list[Release], advisories: list[Any]) -> dict[str, Any]:
    between = notes_between(releases, old.version, new.version)
    fixed = fixed_advisories(advisories, old.version, new.version)
    return {
        "id": f"{eco}:{pkg}:{old.version}->{new.version}",
        "ecosystem": eco,
        "package": pkg,
        "source_repo": repo,
        "from_version": str(old.version),
        "to_version": str(new.version),
        "jump": semver_jump(old.version, new.version),
        "release_notes": format_notes(between),
        "release_urls": [r.url for r in between][:10],
        "advisories": [{"ghsa_id": a.ghsa_id, "summary": a.summary, "severity": a.severity, "url": a.url} for a in fixed],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    fetcher = Fetcher(cache_dir=ROOT / "eval" / ".http-cache")
    pools: dict[str, list[dict[str, Any]]] = {"security": [], "major": [], "minor": [], "patch": []}
    for eco, pkg, repo in PACKAGES:
        releases = list_releases(fetcher, repo, pkg)
        if len(releases) < 3:
            print(f"{pkg}: too few releases, skipped")
            continue
        advisories = list_advisories(fetcher, eco, pkg)
        cands = candidates(releases, rng)
        sec = [(o, n) for jump in cands.values() for o, n in jump if fixed_advisories(advisories, o.version, n.version)]
        if sec:
            pools["security"].append(item(eco, pkg, repo, *rng.choice(sec), releases, advisories))
        for jump, k in (("major", 2), ("minor", 2), ("patch", 2)):
            for old, new in rng.sample(cands[jump], min(k, len(cands[jump]))):
                pools[jump].append(item(eco, pkg, repo, old, new, releases, advisories))
        print(f"{pkg}: {len(releases)} releases, {len(advisories)} advisories, majors {len(cands['major'])}")
    # Balance: every security and major bump, then minors and patches to reach the target.
    rows = pools["security"] + pools["major"]
    seen = {r["id"] for r in rows}
    rest = [r for r in pools["minor"] + pools["patch"] if r["id"] not in seen]
    rng.shuffle(rest)
    rows += rest[: max(0, args.target - len(rows))]
    rows = list({r["id"]: r for r in rows}.values())
    rows.sort(key=lambda r: r["id"])
    # The CI result is simulated (these bumps never ran in a real repository): 80% green, 12% red, 8% still running.
    ci_rng = random.Random(5)
    for r in rows:
        x = ci_rng.random()
        r["ci_status"] = "success" if x < 0.80 else ("failure" if x < 0.92 else "pending")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {j: sum(1 for r in rows if r["jump"] == j) for j in ("major", "minor", "patch")}
    print(f"wrote {len(rows)} updates ({counts}, {sum(1 for r in rows if r['advisories'])} fix an advisory) to {OUT}")


if __name__ == "__main__":
    main()
