from depgate.parse_pr import guess_ecosystem, parse_bump
from depgate.versions import Version, in_range, parse_version, semver_jump


def test_parse_version_forms() -> None:
    assert parse_version("v1.2.3") == Version(1, 2, 3)
    assert parse_version("svelte@5.1.0") == Version(5, 1, 0)
    assert parse_version("2.0") == Version(2, 0, 0)
    assert parse_version("2.0.0rc1").is_prerelease  # type: ignore[union-attr]
    assert parse_version("not a version") is None


def test_semver_jump() -> None:
    v = parse_version
    assert semver_jump(v("1.2.3"), v("2.0.0")) == "major"  # type: ignore[arg-type]
    assert semver_jump(v("1.2.3"), v("1.3.0")) == "minor"  # type: ignore[arg-type]
    assert semver_jump(v("1.2.3"), v("1.2.4")) == "patch"  # type: ignore[arg-type]
    assert semver_jump(v("1.2.3"), v("1.2.3")) == "none"  # type: ignore[arg-type]


def test_advisory_ranges() -> None:
    v = parse_version("1.5.0")
    assert v is not None
    assert in_range(v, ">= 1.0.0, < 1.6.0")
    assert not in_range(v, "< 1.5.0")
    assert in_range(v, "< 0.9.0 || >= 1.4.0, < 1.5.1")
    assert in_range(v, "= 1.5.0")


def test_dependabot_title() -> None:
    b = parse_bump("Bump axios from 1.6.0 to 1.7.2 in /web", branch="dependabot/npm_and_yarn/web/axios-1.7.2")
    assert b is not None
    assert (b.package, b.from_version, b.to_version, b.ecosystem, b.jump) == ("axios", "1.6.0", "1.7.2", "npm", "minor")
    scoped = parse_bump("build(deps-dev): bump @vitejs/plugin-react from 4.0.0 to 5.0.1")
    assert scoped is not None and scoped.package == "@vitejs/plugin-react" and scoped.jump == "major"


def test_renovate_title_and_table() -> None:
    body = "| Package | Change |\n|---|---|\n| [httpx](https://example.test) | `0.27.0` -> `0.28.1` |\n"
    b = parse_bump("chore(deps): update dependency httpx to v0.28.1", body, files=["requirements.txt"])
    assert b is not None
    assert (b.package, b.from_version, b.to_version, b.ecosystem) == ("httpx", "0.27.0", "0.28.1", "pip")


def test_grouped_and_unknown_titles() -> None:
    assert parse_bump("Bump the npm_and_yarn group across 1 directory with 3 updates") is None
    assert parse_bump("Fix login button") is None


def test_ecosystem_guess() -> None:
    assert guess_ecosystem("dependabot/pip/requests-2.32.0", [], "") == "pip"
    assert guess_ecosystem("renovate/x", ["package-lock.json"], "") == "npm"
    assert guess_ecosystem("renovate/x", ["poetry.lock"], "") == "pip"


def test_github_actions_bump() -> None:
    b = parse_bump("Bump actions/checkout from 4 to 5", branch="dependabot/github_actions/actions/checkout-5")
    assert b is not None
    assert (b.package, b.ecosystem, b.jump) == ("actions/checkout", "actions", "major")
