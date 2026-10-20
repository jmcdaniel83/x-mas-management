"""Writing back to the yearly list file.

Edits are line-based so comments, spacing, and ordering stay exactly as written.
The result is re-parsed and checked before it replaces the file.
"""

import json
import re
import tomllib

from xmas.config import ConfigError, Item, list_path

HEADER = re.compile(r"^\s*\[")
KEY_LINE = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")


def _blocks(lines: list[str], group: str) -> list[tuple[int, int]]:
    """(start, end) line ranges of each [[group]] block, header included."""
    header = re.compile(rf"^\s*\[\[\s*{re.escape(group)}\s*\]\]")
    starts = [i for i, line in enumerate(lines) if HEADER.match(line)]
    ranges = []
    for n, start in enumerate(starts):
        if header.match(lines[start]):
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            ranges.append((start, end))
    return ranges


def set_image(year: int, item: Item, image: str) -> None:
    path = list_path(year)
    lines = path.read_text().splitlines(keepends=True)

    target = None
    for start, end in _blocks(lines, item.group):
        try:
            if tomllib.loads("".join(lines[start + 1 : end])).get("url") == item.url:
                target = (start, end)
                break
        except tomllib.TOMLDecodeError:
            continue
    if target is None:
        raise ConfigError(f"{path}: could not find [[{item.group}]] {item.url} to update; was the file edited?")

    start, end = target
    new_line = f"image = {json.dumps(image)}\n"
    key_lines = [i for i in range(start + 1, end) if KEY_LINE.match(lines[i])]
    existing = [i for i in key_lines if KEY_LINE.match(lines[i]).group(1) == "image"]
    if existing:
        lines[existing[0]] = new_line
    else:
        last = key_lines[-1]
        if not lines[last].endswith("\n"):
            lines[last] += "\n"
        lines.insert(last + 1, new_line)

    text = "".join(lines)
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: updating the image would break the file ({e}); set it by hand") from e
    if not any(e.get("url") == item.url and e.get("image") == image for e in doc.get(item.group, [])):
        raise ConfigError(f"{path}: updating the image did not take effect; set it by hand")

    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
