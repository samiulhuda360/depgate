"""A small append-only JSONL response cache, so evaluations and CI replay real responses without calling an API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


class JsonlCache:
    """Maps a request key to a recorded response (with its measured latency and usage)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        if path and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._data[row["request_sha"]] = row

    def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    def put(self, key: str, record: dict[str, Any]) -> None:
        row = {"request_sha": key, **record}
        self._data[key] = row
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def __len__(self) -> int:
        return len(self._data)
