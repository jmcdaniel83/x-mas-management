"""Per-year state written by the tool: resolved images, and later board and pin IDs."""

import json
from pathlib import Path

from xmas.config import data_dir


class State:
    def __init__(self, year: int):
        self.path = data_dir() / "state" / f"{year}.json"
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = {"items": {}, "boards": {}}

    def item(self, key: str) -> dict:
        return self.data["items"].setdefault(key, {})

    def image_path(self, key: str) -> Path | None:
        """Absolute path of the image chosen for an item, if one is set and still on disk."""
        rel = self.data["items"].get(key, {}).get("image")
        if rel and (data_dir() / rel).exists():
            return data_dir() / rel
        return None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n")
        tmp.replace(self.path)
