"""Version parsing, semver jumps and advisory range checks (npm semver and simple PEP 440 versions)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION = re.compile(r"(?:^|[@v/\-_ ])v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?([-.+]?(?:a|b|rc|alpha|beta|pre|dev|canary|next|post)[.\-]?\d*)?", re.I)


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int
    extra: int = 0
    pre: str = ""

    @property
    def is_prerelease(self) -> bool:
        return bool(self.pre) and not self.pre.lstrip(".-+").lower().startswith("post")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}" + (f".{self.extra}" if self.extra else "") + self.pre


def parse_version(text: str) -> Version | None:
    """Finds a version in a tag or string such as `v1.2.3`, `pkg@1.2.3`, `1.2` or `2.0.0rc1`."""
    m = _VERSION.search(" " + text.strip())
    if not m:
        return None
    return Version(int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), int(m.group(4) or 0), (m.group(5) or "").lower())


def semver_jump(old: Version, new: Version) -> str:
    """`major`, `minor`, `patch` or `none` (same version or a downgrade)."""
    if new <= old:
        return "none"
    if new.major != old.major:
        return "major"
    if new.minor != old.minor:
        return "minor"
    return "patch"


def _cmp_ok(v: Version, op: str, target: Version) -> bool:
    key_v, key_t = (v.major, v.minor, v.patch, v.extra), (target.major, target.minor, target.patch, target.extra)
    return {
        "<": key_v < key_t,
        "<=": key_v <= key_t,
        ">": key_v > key_t,
        ">=": key_v >= key_t,
        "=": key_v == key_t,
        "==": key_v == key_t,
    }[op]


def in_range(v: Version, spec: str) -> bool:
    """Checks a GitHub advisory range such as `>= 1.0.0, < 1.6.0` or `< 0.21.1`. `||` alternatives are supported."""
    for alternative in spec.split("||"):
        parts = [p.strip() for p in alternative.split(",") if p.strip()]
        ok = True
        for part in parts:
            m = re.match(r"(<=|>=|==|<|>|=)?\s*(.+)", part)
            target = parse_version(m.group(2)) if m else None
            if not m or target is None:
                ok = False
                break
            if not _cmp_ok(v, m.group(1) or "=", target):
                ok = False
                break
        if ok and parts:
            return True
    return False
