"""Public data about an update: the package's source repository, its release notes and its security advisories.

All lookups are read-only GETs to public endpoints (npm registry, PyPI JSON API, GitHub REST) and are cached on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .versions import Version, in_range, parse_version


@dataclass
class Release:
    tag: str
    version: Version
    body: str
    url: str


@dataclass
class Advisory:
    ghsa_id: str
    summary: str
    severity: str
    url: str
    vulnerable_range: str
    patched: str


class Fetcher:
    """GET JSON with an on-disk cache. A GitHub token is used for api.github.com when GITHUB_TOKEN is set."""

    def __init__(self, cache_dir: Path | None = None, client: httpx.Client | None = None, github_api: str | None = None) -> None:
        self.cache_dir = cache_dir
        self.http = client or httpx.Client(timeout=30, follow_redirects=True)
        self.github_api = (github_api or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        full = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")
        path = self.cache_dir / (hashlib.sha256(full.encode()).hexdigest()[:32] + ".json") if self.cache_dir else None
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        headers = {"User-Agent": "depgate", "Accept": "application/json"}
        if url.startswith(self.github_api) and os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
            headers["Accept"] = "application/vnd.github+json"
        resp = self.http.get(full, headers=headers)
        if resp.status_code == 404:
            data: Any = None
        else:
            resp.raise_for_status()
            data = resp.json()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        return data


def _github_slug(url: str) -> str | None:
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def resolve_repo(fetcher: Fetcher, ecosystem: str, package: str) -> str | None:
    """Finds the GitHub `owner/repo` for a package from its registry metadata."""
    if ecosystem == "actions":
        parts = package.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else None
    if ecosystem == "npm":
        meta = fetcher.get_json(f"https://registry.npmjs.org/{package}")
        repo = (meta or {}).get("repository") or {}
        return _github_slug(repo.get("url", "") if isinstance(repo, dict) else str(repo))
    if ecosystem == "pip":
        meta = fetcher.get_json(f"https://pypi.org/pypi/{package}/json")
        info = (meta or {}).get("info") or {}
        urls = [*(info.get("project_urls") or {}).values(), info.get("home_page") or ""]
        for u in urls:
            slug = _github_slug(u or "")
            if slug:
                return slug
    return None


def tag_matches(tag: str, package: str) -> bool:
    """Monorepos tag every package; keep plain `v1.2.3` tags and tags for this package only."""
    t = tag.strip()
    if "@" in t:
        return t.rsplit("@", 1)[0].lstrip("@").split("/")[-1] == package.rsplit("/", maxsplit=1)[-1]
    return bool(re.match(r"^(v|version[-_ ]?|release[-_ ]?|" + re.escape(package) + r"[-_ ]?v?)?\d", t, re.I))


def list_releases(fetcher: Fetcher, repo: str, package: str, pages: int = 3) -> list[Release]:
    out: list[Release] = []
    for page in range(1, pages + 1):
        batch = fetcher.get_json(f"{fetcher.github_api}/repos/{repo}/releases", {"per_page": 100, "page": page}) or []
        for r in batch:
            if r.get("draft") or r.get("prerelease") or not tag_matches(r.get("tag_name", ""), package):
                continue
            v = parse_version(r["tag_name"])
            if v and not v.is_prerelease:
                out.append(Release(r["tag_name"], v, (r.get("body") or "").strip(), r.get("html_url", "")))
        if len(batch) < 100:
            break
    out.sort(key=lambda r: r.version)
    return out


def notes_between(releases: list[Release], old: Version, new: Version) -> list[Release]:
    """Releases after `old` up to and including `new`, newest first."""
    return sorted([r for r in releases if old < r.version <= new], key=lambda r: r.version, reverse=True)


def format_notes(releases: list[Release], max_chars: int = 8000) -> str:
    parts = []
    for r in releases:
        body = re.sub(r"<!--.*?-->", "", r.body, flags=re.S).strip() or "(no release notes)"
        parts.append(f"## {r.tag}\n{body}\n")
    text = "\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n... (release notes trimmed)"


def list_advisories(fetcher: Fetcher, ecosystem: str, package: str) -> list[Advisory]:
    eco = {"npm": "npm", "pip": "pip"}.get(ecosystem, ecosystem)
    data = fetcher.get_json(f"{fetcher.github_api}/advisories", {"ecosystem": eco, "affects": package, "per_page": 100}) or []
    out = []
    for a in data:
        for vuln in a.get("vulnerabilities") or []:
            pkg = (vuln.get("package") or {}).get("name", "")
            if pkg.lower() != package.lower():
                continue
            out.append(
                Advisory(
                    ghsa_id=a.get("ghsa_id", ""),
                    summary=a.get("summary", ""),
                    severity=a.get("severity", ""),
                    url=a.get("html_url", ""),
                    vulnerable_range=vuln.get("vulnerable_version_range") or "",
                    patched=vuln.get("first_patched_version") or "",
                )
            )
    return out


def fixed_advisories(advisories: list[Advisory], old: Version, new: Version) -> list[Advisory]:
    """Advisories that affect the old version but not the new one."""
    fixed = []
    for a in advisories:
        if a.vulnerable_range and in_range(old, a.vulnerable_range) and not in_range(new, a.vulnerable_range):
            fixed.append(a)
    return fixed
