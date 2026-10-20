"""Resolve every item's image into the local cache.

Items with an `image` (URL or local path) get it downloaded or validated directly.
Items without one get candidate images scraped from their page, for `pick` to choose from.
"""

import hashlib
import io
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from xmas.config import Item, data_dir
from xmas.state import State

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 20
MIN_SIDE = 200  # skip icons, logos, tracking pixels
MAX_CANDIDATES = 12
MAX_URLS_TRIED = 40
MAX_ASPECT = 2.5  # skip banners and ad strips


class FetchError(Exception):
    pass


def cache_dir(item: Item) -> Path:
    return data_dir() / "cache" / "images" / item.key


def rel(path: Path) -> str:
    return str(path.relative_to(data_dir()))


def _download(url: str, referer: str | None = None) -> bytes:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.content


def _normalize(raw: bytes, dest_stem: Path) -> Path:
    """Validate image bytes and save as JPEG (or PNG if it has transparency), which Pinterest accepts."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise FetchError(f"not a readable image ({e})") from e
    if min(img.size) < MIN_SIDE:
        raise FetchError(f"too small ({img.width}x{img.height})")
    if max(img.size) / min(img.size) > MAX_ASPECT:
        raise FetchError(f"banner-shaped ({img.width}x{img.height})")

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        dest = dest_stem.with_suffix(".png")
        img.save(dest, "PNG")
    else:
        dest = dest_stem.with_suffix(".jpg")
        img.convert("RGB").save(dest, "JPEG", quality=92)
    return dest


def _image_urls(html: str, page_url: str) -> list[str]:
    """Candidate image URLs from a product page, most likely first."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    # Amazon keeps the full-size product gallery in inline script data rather than <img> tags.
    # Only the main image's data-a-dynamic-image is used, since carousels of other products have it too.
    gallery = [json.loads(f'"{u}"') for u in re.findall(r'"hiRes":"(https://[^"]+)"', html)]
    landing = soup.find(id="landingImage")
    if landing and landing.get("data-a-dynamic-image"):
        try:
            sizes = json.loads(landing["data-a-dynamic-image"])
            gallery.append(max(sizes, key=lambda u: sizes[u][0] * sizes[u][1]))
        except (json.JSONDecodeError, ValueError, TypeError, IndexError):
            pass
    urls.extend(gallery)

    for prop in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            urls.append(tag.get("content", ""))

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            urls.extend(_jsonld_images(json.loads(script.string or "")))
        except json.JSONDecodeError:
            pass

    for tag in soup.find_all("link", rel="image_src"):
        urls.append(tag.get("href", ""))

    # with a structured gallery, the remaining <img> tags are mostly ads and related products
    for img in [] if gallery else soup.find_all("img"):
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            # last srcset entry is conventionally the largest
            urls.append(srcset.split(",")[-1].strip().split(" ")[0])
        urls.append(img.get("data-src") or img.get("data-old-hires") or img.get("src") or "")

    seen = set()
    result = []
    for u in urls:
        u = u.strip()
        if not u or u.startswith("data:"):
            continue
        u = urljoin(page_url, u)
        # Amazon serves one image at many sizes via a ._SL1500_. style modifier; keep the first (largest) only
        base = re.sub(r"\._[^/]*_\.(?=\w+$)", ".", u)
        if urlparse(u).path.lower().endswith(".svg") or base in seen:
            continue
        seen.add(base)
        result.append(u)
    return result


def _jsonld_images(node) -> list[str]:
    if isinstance(node, list):
        return [u for n in node for u in _jsonld_images(n)]
    if not isinstance(node, dict):
        return []
    found = []
    image = node.get("image")
    if isinstance(image, str):
        found.append(image)
    elif isinstance(image, list):
        found.extend(i if isinstance(i, str) else i.get("url", "") for i in image if isinstance(i, (str, dict)))
    elif isinstance(image, dict):
        found.append(image.get("url", ""))
    for child in node.get("@graph", []):
        found.extend(_jsonld_images(child))
    return found


def _provided_image(item: Item, state: State, refresh: bool) -> str:
    entry = state.item(item.key)
    if entry.get("source") == item.image and state.image_path(item.key) and not refresh:
        return "cached"

    is_url = item.image.startswith(("http://", "https://"))
    if is_url:
        raw = _download(item.image, referer=item.url)
    else:
        local = data_dir() / item.image
        if not local.exists():
            raise FetchError(f"image file {local} not found")
        raw = local.read_bytes()

    out = cache_dir(item)
    out.mkdir(parents=True, exist_ok=True)
    dest = _normalize(raw, out / "provided")
    entry.update(image=rel(dest), source=item.image)
    return "downloaded" if is_url else "validated"


def _scrape_candidates(item: Item, refresh: bool) -> int:
    out = cache_dir(item)
    manifest = out / "candidates.json"
    if manifest.exists() and not refresh:
        return len(json.loads(manifest.read_text()))

    for f in out.glob("candidate-*"):
        f.unlink()
    out.mkdir(parents=True, exist_ok=True)

    try:
        html = _download(item.url).decode("utf-8", errors="replace")
    except requests.RequestException as e:
        raise FetchError(f"could not load page ({e})") from e

    candidates = []
    hashes = set()
    for url in _image_urls(html, item.url)[:MAX_URLS_TRIED]:
        if len(candidates) >= MAX_CANDIDATES:
            break
        try:
            raw = _download(url, referer=item.url)
        except requests.RequestException:
            continue
        digest = hashlib.sha1(raw).hexdigest()
        if digest in hashes:
            continue
        try:
            dest = _normalize(raw, out / f"candidate-{len(candidates) + 1:02d}")
        except FetchError:
            continue
        hashes.add(digest)
        candidates.append({"file": rel(dest), "source": url})

    manifest.write_text(json.dumps(candidates, indent=2) + "\n")
    if not candidates:
        raise FetchError("no usable images found on the page (site may block scraping); set `image` for this item")
    return len(candidates)


def run(items: list[Item], state: State, refresh: bool = False) -> int:
    failures = 0
    for item in items:
        label = f"[{item.group}] {item.name}"
        try:
            if item.image:
                print(f"  {label}: image {_provided_image(item, state, refresh)}")
            else:
                # no `image` in the list file (never set, or removed to re-pick), so nothing earlier applies
                state.data["items"].pop(item.key, None)
                count = _scrape_candidates(item, refresh)
                print(f"  {label}: {count} candidate(s), run `pick` to choose")
        except (FetchError, requests.RequestException) as e:
            failures += 1
            print(f"  {label}: FAILED - {e}")
        state.save()
    return failures
