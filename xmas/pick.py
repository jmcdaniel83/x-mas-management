"""Local web page for choosing each item's image from its scraped candidates."""

import html
import json
import re
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from xmas import listfile
from xmas.config import Item, data_dir
from xmas.fetch import cache_dir
from xmas.state import State

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pick Images {year}</title>
<style>
  :root {{ --bg: #faf7f2; --card: #fff; --text: #222; --muted: #666; --accent: #b3261e; --border: #ddd; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #1b1b1b; --card: #262626; --text: #eee; --muted: #aaa; --accent: #ff6b5e; --border: #3a3a3a; }}
  }}
  body {{ background: var(--bg); color: var(--text); font: 15px/1.4 system-ui, sans-serif; margin: 0; padding: 16px; }}
  header {{ display: flex; justify-content: space-between; align-items: center; max-width: 1100px; margin: 0 auto 16px; gap: 12px; }}
  h1 {{ font-size: 20px; margin: 0; }}
  #progress {{ color: var(--muted); }}
  button {{ background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: 8px 16px; font-size: 15px; cursor: pointer; }}
  section {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; max-width: 1100px; margin: 0 auto 16px; }}
  section h2 {{ font-size: 16px; margin: 0 0 2px; }}
  section .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 10px; overflow-wrap: anywhere; }}
  section .meta a {{ color: inherit; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; }}
  .grid img {{ width: 100%; aspect-ratio: 1; object-fit: contain; background: #fff; border: 3px solid transparent; border-radius: 8px; cursor: pointer; }}
  .grid img:hover {{ border-color: var(--border); }}
  .grid img.chosen {{ border-color: var(--accent); }}
  section.done h2::after {{ content: " ✓"; color: var(--accent); }}
  #closed {{ display: none; text-align: center; padding: 40px; }}
</style>
</head>
<body>
<header>
  <h1>Pick images for {year}</h1>
  <span id="progress"></span>
  <button id="finish">Done</button>
</header>
<main>{sections}</main>
<p id="closed">Saved. You can close this tab.</p>
<script>
  const sections = document.querySelectorAll("section");
  function progress() {{
    const done = document.querySelectorAll("section.done").length;
    document.getElementById("progress").textContent = done + " of " + sections.length + " picked";
  }}
  document.querySelectorAll(".grid img").forEach(img => img.addEventListener("click", async () => {{
    const section = img.closest("section");
    const res = await fetch("/pick", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ key: section.dataset.key, file: img.dataset.file }}),
    }});
    if (!res.ok) {{ alert(await res.text()); return; }}
    section.querySelectorAll("img").forEach(i => i.classList.toggle("chosen", i === img));
    section.classList.add("done");
    progress();
  }}));
  document.getElementById("finish").addEventListener("click", async () => {{
    await fetch("/done", {{ method: "POST" }});
    document.querySelector("main").style.display = "none";
    document.querySelector("header").style.display = "none";
    document.getElementById("closed").style.display = "block";
  }});
  progress();
</script>
</body>
</html>
"""


def _candidates(item: Item) -> list[dict]:
    manifest = cache_dir(item) / "candidates.json"
    return json.loads(manifest.read_text()) if manifest.exists() else []


def _section(item: Item, chosen: str | None) -> str:
    imgs = "".join(
        f'<img src="/img?f={html.escape(c["file"])}" data-file="{html.escape(c["file"])}"'
        f'{" class=chosen" if c["file"] == chosen else ""} loading="lazy" alt="">'
        for c in _candidates(item)
    )
    return (
        f'<section data-key="{item.key}"{" class=done" if chosen else ""}>'
        f"<h2>{html.escape(item.name)}</h2>"
        f'<div class="meta">{html.escape(item.group)} · '
        f'<a href="{html.escape(item.url)}" target="_blank" rel="noopener">{html.escape(item.url)}</a></div>'
        f'<div class="grid">{imgs}</div></section>'
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def _pick_target(year: int, item: Item, ext: str, items: list[Item], state: State) -> str:
    """Path (relative to data/) to save a pick to, never colliding with another item's or a user-provided image."""
    own = state.data["items"].get(item.key, {}).get("picked_to")
    taken = {i.image for i in items if i.image and i.key != item.key}
    taken |= {e["picked_to"] for k, e in state.data["items"].items() if k != item.key and e.get("picked_to")}
    stem = f"images/{year}/{_slug(item.group)}/{_slug(item.name)}"
    for n in range(1, 1000):
        rel = f"{stem}{'' if n == 1 else f'-{n}'}{ext}"
        if rel == own or (rel not in taken and not (data_dir() / rel).exists()):
            return rel
    raise RuntimeError(f"no free filename for {stem}")


def save_pick(year: int, item: Item, candidate: str, items: list[Item], state: State) -> str:
    """Copy the chosen candidate out of the cache and point the list file's entry at it."""
    entry = state.item(item.key)
    target = _pick_target(year, item, (data_dir() / candidate).suffix, items, state)
    dest = data_dir() / target
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_dir() / candidate, dest)

    old = entry.get("picked_to")
    if old and old != target:
        # re-picked with a different extension; the old file was ours, so remove it
        (data_dir() / old).unlink(missing_ok=True)

    listfile.set_image(year, item, target)
    entry.clear()
    entry.update(image=target, source=target, picked=candidate, picked_to=target)
    state.save()
    return target


def _is_own_pick(item: Item, state: State) -> bool:
    entry = state.data["items"].get(item.key, {})
    return bool(item.image) and entry.get("picked_to") == item.image


def run(year: int, items: list[Item], state: State, port: int = 8086, show_all: bool = False) -> int:
    pickable = [i for i in items if not i.image and _candidates(i)]
    if show_all:
        # items whose image came from an earlier pick can be re-picked; user-provided images are left alone
        pickable += [i for i in items if _is_own_pick(i, state) and _candidates(i)]
    if not pickable:
        print("Nothing to pick. Run `fetch` first, or use --all to change existing picks.")
        return 0

    by_key = {i.key: i for i in pickable}
    lock = threading.Lock()

    def chosen(item: Item) -> str | None:
        return state.data["items"].get(item.key, {}).get("picked")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                sections = "".join(_section(i, chosen(i)) for i in pickable)
                self._send(200, PAGE.format(year=year, sections=sections).encode(), "text/html; charset=utf-8")
            elif url.path == "/img":
                rel = parse_qs(url.query).get("f", [""])[0]
                path = (data_dir() / rel).resolve()
                cache_root = (data_dir() / "cache").resolve()
                if not path.is_relative_to(cache_root) or not path.is_file():
                    self._send(404, b"not found")
                    return
                ctype = "image/png" if path.suffix == ".png" else "image/jpeg"
                self._send(200, path.read_bytes(), ctype)
            else:
                self._send(404, b"not found")

        def do_POST(self):
            if self.path == "/done":
                self._send(200, b"ok")
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            if self.path != "/pick":
                self._send(404, b"not found")
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            item = by_key.get(body.get("key"))
            if not item or body.get("file") not in {c["file"] for c in _candidates(item)}:
                self._send(400, b"unknown item or image")
                return
            try:
                with lock:
                    target = save_pick(year, item, body["file"], items, state)
            except Exception as e:
                print(f"  [{item.group}] {item.name}: FAILED - {e}")
                self._send(500, f"Could not save pick: {e}".encode())
                return
            print(f"  [{item.group}] {item.name}: image = \"{target}\"")
            self._send(200, b"ok")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Picking images for {len(pickable)} item(s) at {url}  (click Done in the page, or Ctrl+C, when finished)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    remaining = [i for i in items if not i.image and not state.image_path(i.key)]
    if remaining:
        print(f"{len(remaining)} item(s) still without an image:")
        for i in remaining:
            print(f"  [{i.group}] {i.name}")
    return 0
