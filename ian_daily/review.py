from __future__ import annotations

import functools
import http.server
import os
import secrets

from . import config
from .site import build_site


def run_review_server(host: str = "127.0.0.1", port: int = 5211, access_token: str = "") -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("预览服务只允许绑定本机")
    if not (config.SITE_DIR / "index.html").exists():
        build_site()
    token = access_token or os.environ.get("IAN_DAILY_REVIEW_TOKEN") or secrets.token_urlsafe(24)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/health"):
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
            if f"token={token}" not in self.path and self.headers.get("Cookie") != f"ian_token={token}":
                self.send_error(403, "Missing preview token"); return
            if f"token={token}" in self.path:
                self.send_response(302); self.send_header("Set-Cookie", f"ian_token={token}; SameSite=Strict"); self.send_header("Location", "/"); self.end_headers(); return
            super().do_GET()

    handler = functools.partial(Handler, directory=str(config.SITE_DIR))
    print(f"预览地址：http://{host}:{port}/?token={token}")
    http.server.ThreadingHTTPServer((host, port), handler).serve_forever()
