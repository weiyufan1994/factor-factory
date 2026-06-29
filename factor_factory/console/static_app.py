from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs

from factor_factory.console.discovery import discover_miner_campaigns
from factor_factory.console.readers import read_miner_campaign
from factor_factory.console.task_manifest import create_miner_campaign_task, read_console_tasks
from factor_factory.console.summary import render_dashboard


def build_console_html(roots: Iterable[str | Path]) -> str:
    root_list = [Path(root) for root in roots]
    workspaces = discover_miner_campaigns(root_list)
    summaries = [read_miner_campaign(workspace) for workspace in workspaces]
    tasks = []
    for root in root_list:
        tasks.extend(read_console_tasks(root))
    return render_dashboard(summaries, tasks)


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

        def do_POST(self) -> None:
            if self.path != "/tasks/miner":
                self.send_error(404, "Not found")
                return
            if not roots:
                self.send_error(400, "No writable Console root configured")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            payload = self.rfile.read(length).decode("utf-8")
            fields = parse_qs(payload, keep_blank_values=True)
            catalogs = [
                item.strip()
                for value in fields.get("catalogs", [])
                for item in value.replace(",", "\n").splitlines()
                if item.strip()
            ]
            try:
                create_miner_campaign_task(
                    root=roots[0],
                    campaign_id=_field(fields, "campaign_id"),
                    execution_workspace=_field(fields, "execution_workspace"),
                    catalogs=catalogs,
                    screen_window=_field(fields, "screen_window", "2016-01-01..2025-07-11"),
                    universe=_field(fields, "universe", "current_data_api_catalog"),
                )
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return ConsoleHandler


def _field(fields: dict[str, list[str]], name: str, default: str = "") -> str:
    values = fields.get(name)
    if not values:
        return default
    return values[0].strip() or default


def serve_console(roots: list[str | Path], host: str, port: int) -> None:
    server = build_console_server(roots, host, port)
    serve_console_server(server)


def build_console_server(roots: list[str | Path], host: str, port: int) -> ThreadingHTTPServer:
    root_paths = [Path(root) for root in roots]
    return ThreadingHTTPServer((host, port), make_handler(root_paths))


def serve_console_server(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever()
    finally:
        server.server_close()
