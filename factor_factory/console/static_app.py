from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable

from factor_factory.console.discovery import discover_miner_campaigns
from factor_factory.console.readers import read_miner_campaign
from factor_factory.console.summary import render_dashboard


def build_console_html(roots: Iterable[str | Path]) -> str:
    workspaces = discover_miner_campaigns(list(roots))
    summaries = [read_miner_campaign(workspace) for workspace in workspaces]
    return render_dashboard(summaries)


def make_handler(roots: list[Path]) -> type[BaseHTTPRequestHandler]:
    class ConsoleHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/index.html"}:
                self.send_error(404, "Not found")
                return
            html = build_console_html(roots).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ConsoleHandler


def serve_console(roots: list[str | Path], host: str, port: int) -> None:
    root_paths = [Path(root) for root in roots]
    server = ThreadingHTTPServer((host, port), make_handler(root_paths))
    try:
        server.serve_forever()
    finally:
        server.server_close()
