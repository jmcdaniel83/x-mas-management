"""Loading and validating groups.toml and the yearly list file."""

import hashlib
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("XMAS_DATA", "data")).resolve()


@dataclass(frozen=True)
class Group:
    key: str
    board_name_template: str
    collaborators: tuple[str, ...]

    def board_name(self, year: int) -> str:
        return self.board_name_template.format(year=year)


@dataclass(frozen=True)
class Item:
    group: str
    name: str
    url: str
    image: str | None
    description: str | None

    @property
    def key(self) -> str:
        """Stable ID for this item, used in state and as the cache directory name."""
        return hashlib.sha1(f"{self.group}\n{self.url}".encode()).hexdigest()[:12]


def _load_toml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path} not found")
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e


def load_groups() -> dict[str, Group]:
    path = data_dir() / "groups.toml"
    groups = {}
    for key, table in _load_toml(path).items():
        if not isinstance(table, dict) or "board_name" not in table:
            raise ConfigError(f"{path}: [{key}] needs a board_name")
        groups[key] = Group(
            key=key,
            board_name_template=table["board_name"],
            collaborators=tuple(table.get("collaborators", [])),
        )
    return groups


def list_path(year: int) -> Path:
    return data_dir() / "lists" / f"xmas-list-{year}.toml"


def load_items(year: int, groups: dict[str, Group]) -> list[Item]:
    path = list_path(year)
    items = []
    seen = set()
    for group, entries in _load_toml(path).items():
        if group not in groups:
            raise ConfigError(f"{path}: [[{group}]] is not defined in groups.toml (known: {', '.join(groups)})")
        if not isinstance(entries, list):
            raise ConfigError(f"{path}: use [[{group}]] (double brackets) for each item")
        for i, entry in enumerate(entries, 1):
            missing = [k for k in ("name", "url") if not entry.get(k)]
            if missing:
                raise ConfigError(f"{path}: [[{group}]] item #{i} is missing {', '.join(missing)}")
            if not entry["url"].startswith(("http://", "https://")):
                raise ConfigError(f"{path}: [[{group}]] {entry['name']!r} url must start with https:// (got {entry['url'][:40]!r}...)")
            item = Item(
                group=group,
                name=entry["name"],
                url=entry["url"],
                image=entry.get("image"),
                description=entry.get("description"),
            )
            if item.key in seen:
                raise ConfigError(f"{path}: {item.url} appears twice in [[{group}]]")
            seen.add(item.key)
            items.append(item)
    return items
