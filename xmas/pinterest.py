"""Minimal Pinterest API v5 client: OAuth tokens, boards, and pins."""

import base64
import json
import os
import time
from pathlib import Path

import requests

from xmas.config import data_dir

API = "https://api.pinterest.com/v5"
SANDBOX_API = "https://api-sandbox.pinterest.com/v5"
AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
SCOPES = [
    "user_accounts:read",
    "boards:read",
    "boards:read_secret",
    "boards:write",
    "boards:write_secret",
    "pins:read",
    "pins:write",
]
REFRESH_MARGIN = 24 * 3600  # refresh the access token when it has less than a day left
TIMEOUT = 30


class PinterestError(Exception):
    pass


def token_file() -> Path:
    """OAuth tokens live with the other personal data, outside git."""
    return data_dir() / ".token.json"


def load_env(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines from .env into the environment without overriding existing values."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def app_credentials() -> tuple[str, str]:
    load_env()
    app_id = os.environ.get("PINTEREST_APP_ID")
    secret = os.environ.get("PINTEREST_APP_SECRET")
    if not app_id or not secret:
        raise PinterestError("PINTEREST_APP_ID and PINTEREST_APP_SECRET must be set (see .env.example)")
    return app_id, secret


def api_base() -> str:
    load_env()
    return SANDBOX_API if os.environ.get("PINTEREST_SANDBOX", "").lower() in ("1", "true", "yes") else API


def _token_request(data: dict) -> dict:
    app_id, secret = app_credentials()
    basic = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
    resp = requests.post(
        f"{API}/oauth/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise PinterestError(f"token request failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def save_token(token: dict) -> None:
    now = int(time.time())
    saved = {
        "access_token": token["access_token"],
        "access_expires_at": now + int(token.get("expires_in", 0)),
        "scope": token.get("scope", ""),
    }
    if token.get("refresh_token"):
        saved["refresh_token"] = token["refresh_token"]
        saved["refresh_expires_at"] = now + int(token.get("refresh_token_expires_in", 0))
    elif token_file().exists():
        # refresh responses may not include a new refresh token; keep the existing one
        old = json.loads(token_file().read_text())
        saved["refresh_token"] = old.get("refresh_token")
        saved["refresh_expires_at"] = old.get("refresh_expires_at")
    token_file().write_text(json.dumps(saved, indent=2) + "\n")
    token_file().chmod(0o600)


def exchange_code(code: str, redirect_uri: str) -> None:
    save_token(_token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}))


def has_token() -> bool:
    return token_file().exists()


def access_token() -> str:
    if not token_file().exists():
        raise PinterestError("not logged in; run `xmas auth` first")
    token = json.loads(token_file().read_text())
    now = time.time()
    if token["access_expires_at"] - now > REFRESH_MARGIN:
        return token["access_token"]
    if not token.get("refresh_token") or (token.get("refresh_expires_at") or 0) < now:
        raise PinterestError("login expired; run `xmas auth` again")
    save_token(_token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}))
    return json.loads(token_file().read_text())["access_token"]


class Client:
    def __init__(self):
        self.base = api_base()
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token()}"

    def _call(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(3):
            resp = self.session.request(method, f"{self.base}{path}", timeout=TIMEOUT, **kwargs)
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 ** (attempt + 2))
                continue
            break
        if not resp.ok:
            try:
                detail = resp.json().get("message", resp.text)
            except ValueError:
                detail = resp.text
            raise PinterestError(f"{method} {path}: {resp.status_code} {detail[:300]}")
        return resp.json() if resp.content else {}

    def user(self) -> dict:
        return self._call("GET", "/user_account")

    def boards(self) -> list[dict]:
        boards, bookmark = [], None
        while True:
            params = {"page_size": 100, "privacy": "ALL"}
            if bookmark:
                params["bookmark"] = bookmark
            page = self._call("GET", "/boards", params=params)
            boards.extend(page.get("items", []))
            bookmark = page.get("bookmark")
            if not bookmark:
                return boards

    def board(self, board_id: str) -> dict | None:
        try:
            return self._call("GET", f"/boards/{board_id}")
        except PinterestError as e:
            if " 404 " in str(e):
                return None
            raise

    def create_board(self, name: str, privacy: str = "PUBLIC", description: str = "") -> dict:
        return self._call("POST", "/boards", json={"name": name, "privacy": privacy, "description": description})

    def set_board_privacy(self, board_id: str, privacy: str) -> dict:
        return self._call("PATCH", f"/boards/{board_id}", json={"privacy": privacy})

    def create_pin(self, board_id: str, title: str, link: str, image: Path, description: str | None) -> dict:
        body = {
            "board_id": board_id,
            "title": title[:100],
            "link": link,
            "alt_text": title[:500],
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/png" if image.suffix == ".png" else "image/jpeg",
                "data": base64.b64encode(image.read_bytes()).decode(),
            },
        }
        if description:
            body["description"] = description[:800]
        return self._call("POST", "/pins", json=body)
