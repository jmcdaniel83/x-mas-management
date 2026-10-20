"""One-time OAuth login: open Pinterest's consent page and catch the redirect locally."""

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from xmas import pinterest

DEFAULT_PORT = 8085


def run(port: int = DEFAULT_PORT) -> int:
    app_id, _ = pinterest.app_credentials()
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            if url.path != "/callback":
                self.send_error(404)
                return
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            if params.get("state") != state:
                result["error"] = "state mismatch (possible stale or forged redirect)"
            elif "error" in params:
                result["error"] = params.get("error_description") or params["error"]
            elif "code" not in params:
                result["error"] = "no authorization code in redirect"
            else:
                result["code"] = params["code"]

            message = "Logged in. You can close this tab." if "code" in result else f"Login failed: {result['error']}"
            body = f"<!doctype html><meta charset=utf-8><title>xmas auth</title><p>{message}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = HTTPServer(("127.0.0.1", port), Handler)
    authorize = pinterest.AUTHORIZE_URL + "?" + urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(pinterest.SCOPES),
        "state": state,
    })
    print(f"Opening Pinterest to log in. If no browser opens, visit:\n  {authorize}")
    print(f"(The app's redirect URI must be set to {redirect_uri})")
    webbrowser.open(authorize)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 1
    finally:
        server.server_close()

    if "error" in result:
        print(f"error: {result['error']}")
        return 1
    pinterest.exchange_code(result["code"], redirect_uri)
    user = pinterest.Client().user()
    print(f"Logged in as {user.get('username', '?')}. Token saved to {pinterest.token_file()}")
    return 0
