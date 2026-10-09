"""How does this repository use the package? A grep for its imports and for the symbols the release notes mention.

The result is a short list of `path:line: code` strings: that list, not the source code, is what is sent to a model.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

SOURCE_EXT = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx", ".vue", ".svelte", ".py")
MANIFESTS = ("package.json", "pyproject.toml", "setup.cfg", ".nvmrc", ".python-version", "runtime.txt")
CONFIG_EXT = (".json", ".toml", ".ini", ".cfg", ".yml", ".yaml")
CONFIG_NAMES = ("Makefile", "Dockerfile", "tox.ini")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__", ".next", "coverage", ".tox", "site-packages"}
# PyPI names whose import name differs.
IMPORT_NAMES: dict[str, list[str]] = {
    "pyjwt": ["jwt"],
    "python-dotenv": ["dotenv"],
    "attrs": ["attrs", "attr"],
    "pillow": ["PIL"],
    "pyyaml": ["yaml"],
    "beautifulsoup4": ["bs4"],
    "scikit-learn": ["sklearn"],
    "python-dateutil": ["dateutil"],
    "jinja2": ["jinja2"],
}
STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "now",
    "new",
    "fix",
    "fixes",
    "fixed",
    "add",
    "added",
    "remove",
    "removed",
    "update",
    "updated",
    "support",
    "true",
    "false",
    "null",
    "none",
    "undefined",
    "error",
    "errors",
    "default",
    "option",
    "options",
    "type",
    "types",
    "value",
    "values",
    "function",
    "method",
    "class",
    "import",
    "require",
    "export",
    "return",
    "async",
    "await",
    "const",
    "string",
    "number",
    "object",
    "array",
    "index",
    "test",
    "tests",
    "docs",
    "readme",
    "changelog",
    "release",
    "version",
    "breaking",
    "node",
    "python",
}


def import_names(package: str, ecosystem: str) -> list[str]:
    if ecosystem == "pip":
        return IMPORT_NAMES.get(package.lower(), [package.lower().replace("-", "_")])
    return [package]


def import_pattern(package: str, ecosystem: str) -> re.Pattern[str]:
    names = "|".join(re.escape(n) for n in import_names(package, ecosystem))
    if ecosystem == "actions":
        return re.compile(rf"uses:\s*['\"]?{re.escape(package)}(?:/[^@\s]*)?@")
    if ecosystem == "pip":
        return re.compile(rf"^\s*(?:import\s+(?:{names})\b|from\s+(?:{names})(?:\.[\w.]+)?\s+import\b)")
    return re.compile(
        rf"""(?:require\(\s*['"](?:{names})(?:/[^'"]*)?['"]\s*\)|from\s+['"](?:{names})(?:/[^'"]*)?['"]|import\s+['"](?:{names})(?:/[^'"]*)?['"]|import\(\s*['"](?:{names})['"])"""
    )


def symbols_from_notes(notes: str, package: str, limit: int = 60) -> list[str]:
    """Identifiers the release notes mention: code spans, calls and dotted names."""
    found: list[str] = []
    candidates = re.findall(r"`([^`\n]{2,60})`", notes)
    candidates += re.findall(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\(\)", notes)
    for c in candidates:
        for token in re.findall(r"[A-Za-z_$][\w$]{2,}", c):
            low = token.lower()
            if low in STOP or low == package.lower() or token.isdigit():
                continue
            if token not in found:
                found.append(token)
    return found[:limit]


def iter_files(root: Path) -> Iterable[tuple[str, str]]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and (not d.startswith(".") or d == ".github")]
        for name in filenames:
            if name.endswith(SOURCE_EXT + CONFIG_EXT) or name in MANIFESTS or name in CONFIG_NAMES:
                path = Path(dirpath) / name
                try:
                    if path.stat().st_size > 400_000:
                        continue
                    yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue


def runtime_lines(path: str, text: str) -> list[str]:
    """Declared runtime versions: package.json engines, requires-python, .nvmrc and friends."""
    out = []
    name = path.rsplit("/", 1)[-1]
    if name in (".nvmrc", ".python-version", "runtime.txt"):
        return [f"{path}:1: {text.strip()[:80]}"]
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(r'"(node|npm)"\s*:|"engines"|requires[-_]python|python_requires', line):
            out.append(f"{path}:{i}: {line.strip()[:160]}")
    return out


def find_usage(package: str, ecosystem: str, notes: str, files: Mapping[str, str] | Path, max_lines: int = 25) -> list[str]:
    """Import lines, lines that use a symbol from the notes, and declared runtimes. Capped at `max_lines`."""
    source = files.items() if isinstance(files, Mapping) else iter_files(files)
    pattern = import_pattern(package, ecosystem)
    symbols = symbols_from_notes(notes, package)
    sym_re = re.compile(r"(?<![\w$])(" + "|".join(re.escape(s) for s in symbols) + r")(?![\w$])") if symbols else None
    imports: list[str] = []
    uses: list[str] = []
    runtime: list[str] = []
    short = package.rsplit("/", maxsplit=1)[-1].lower()
    word = re.compile(rf"(?<![\w@/.-]){re.escape(short)}(?![\w-])", re.I)
    for path, text in source:
        name = path.rsplit("/", 1)[-1]
        lines = text.splitlines()
        if ecosystem == "actions":
            # GitHub Actions: the usage is every workflow step that runs the action, with its inputs.
            for i, line in enumerate(lines):
                if pattern.search(line):
                    imports.append(f"{path}:{i + 1}: {line.strip()[:160]}")
                    uses += [
                        f"{path}:{j + 1}: {lines[j].strip()[:160]}"
                        for j in range(i + 1, min(i + 6, len(lines)))
                        if lines[j].strip() and not lines[j].lstrip().startswith("- ")
                    ][:4]
            continue
        if name in MANIFESTS:
            runtime += runtime_lines(path, text)
        if short in name.lower() or (name.endswith((".svelte", ".vue")) and short in ("svelte", "vue")):
            # The package's own config file (jest.config.js, tox.ini, App.svelte): its settings are the usage.
            configs = [f"{path}:{i + 1}: {line.strip()[:160]}" for i, line in enumerate(lines) if line.strip() and not line.strip().startswith(("#", "//"))]
            uses += configs[:12]
            continue
        if name.endswith(CONFIG_EXT) or name in CONFIG_NAMES:
            # Scripts and tool sections that run the package (`poetry install`, `[tool.black]`, "test": "jest").
            uses += [
                f"{path}:{i + 1}: {line.strip()[:160]}"
                for i, line in enumerate(lines)
                if word.search(line) and not re.search(r'^\s*"?' + re.escape(short) + r'"?\s*[:=]\s*"?[~^<>=\d]', line, re.I)
            ][:8]
            continue
        hits = [i for i, line in enumerate(lines) if pattern.search(line)]
        if not hits:
            continue
        aliases = set()
        for i in hits:
            imports.append(f"{path}:{i + 1}: {lines[i].strip()[:160]}")
            aliases.update(re.findall(r"(?:const|let|var|import)\s+\{?\s*([\w$, ]+?)\s*\}?\s*(?:=|from)", lines[i]))
            aliases.update(re.findall(r"\bas\s+(\w+)", lines[i]))
        names = {a.strip() for group in aliases for a in group.split(",") if a.strip()}
        alias_re = re.compile(r"(?<![\w$])(" + "|".join(re.escape(n) for n in names) + r")[.(]") if names else None
        for i, line in enumerate(lines):
            if i in hits or not line.strip() or line.strip().startswith(("#", "//")):
                continue
            if (sym_re and sym_re.search(line)) or (alias_re and alias_re.search(line)):
                uses.append(f"{path}:{i + 1}: {line.strip()[:160]}")
    combined = imports[:8] + runtime[:4]
    combined += uses[: max(0, max_lines - len(combined))]
    return combined
