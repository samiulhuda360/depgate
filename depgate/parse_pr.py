"""Reads the package and versions out of a Dependabot or Renovate pull request."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .versions import parse_version, semver_jump

_DEPENDABOT = re.compile(r"(?i)\bbump\s+(?P<pkg>[@\w./-]+)\s+from\s+v?(?P<old>[\w.+-]+)\s+to\s+v?(?P<new>[\w.+-]+)")
# Dependabot words a version-range update (pip, poetry, uv) as "Update pyyaml requirement from >=6.0 to >=6.0.3".
_DEPENDABOT_REQUIREMENT = re.compile(r"(?i)\bupdate\s+(?P<pkg>[@\w./-]+)\s+requirement\s+from\s+(?P<old>\S+)\s+to\s+(?P<new>\S+)")
_SPEC_VERSION = re.compile(r"\d[\w.+-]*")
_RENOVATE = re.compile(r"(?i)\bupdate\s+(?:dependency\s+)?(?P<pkg>[@\w./-]+)\s+to\s+v?(?P<new>[\w.+-]+)")
_RENOVATE_TABLE = re.compile(r"\|\s*\[?(?P<pkg>[@\w./-]+)\]?(?:\([^)]*\))?\s*\|.*?`[~^=<>]*v?(?P<old>\d[\w.+-]*)`\s*(?:->|→)\s*`[~^=<>]*v?(?P<new>\d[\w.+-]*)`")
_GROUP = re.compile(r"(?i)\bbump the .+ group\b|\bupdate .+ (?:packages|monorepo)\b|\bwith \d+ updates\b")


@dataclass
class ParsedBump:
    package: str
    from_version: str
    to_version: str
    ecosystem: str
    jump: str


def guess_ecosystem(branch: str, files: list[str], body: str) -> str:
    b = branch.lower()
    if "github_actions" in b or (files and all(f.startswith(".github/") for f in files)):
        return "actions"
    if "npm_and_yarn" in b or "/npm" in b:
        return "npm"
    if "/pip" in b or "/uv" in b or "/poetry" in b:
        return "pip"
    names = " ".join(files).lower()
    if any(n in names for n in ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml")):
        return "npm"
    if any(n in names for n in ("requirements", "pyproject.toml", "poetry.lock", "uv.lock", "setup.cfg", "pipfile")):
        return "pip"
    if re.search(r"(?i)\bpypi\b", body):
        return "pip"
    return "npm"


def _spec_floor(spec: str) -> str:
    """The first version number in a requirement specifier: ">=6.0,<7" -> "6.0"."""
    m = _SPEC_VERSION.search(spec)
    return m.group(0) if m else ""


def parse_bump(title: str, body: str = "", branch: str = "", files: list[str] | None = None) -> ParsedBump | None:
    """Returns the single package bump the PR describes, or None for grouped or unrecognised PRs."""
    if _GROUP.search(title):
        return None
    pkg = old = new = ""
    if m := _DEPENDABOT.search(title):
        pkg, old, new = m.group("pkg"), m.group("old"), m.group("new")
    elif m := _DEPENDABOT_REQUIREMENT.search(title):
        # A specifier such as ">=6.0,<7" is judged by the lowest version it now allows.
        pkg, old, new = m.group("pkg"), _spec_floor(m.group("old")), _spec_floor(m.group("new"))
    elif m := _RENOVATE.search(title):
        pkg, new = m.group("pkg"), m.group("new")
        for row in _RENOVATE_TABLE.finditer(body):
            if row.group("pkg").lower() == pkg.lower():
                old, new = row.group("old"), row.group("new")
                break
    if not pkg or not new:
        return None
    vo, vn = parse_version(old) if old else None, parse_version(new)
    jump = semver_jump(vo, vn) if vo and vn else "unknown"
    return ParsedBump(pkg, old, new, guess_ecosystem(branch, files or [], body), jump)
