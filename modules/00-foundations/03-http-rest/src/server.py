"""
Serve an OrdersAPI over real HTTP with the standard library's http.server.

Parsing HTTP was lesson 1. Here http.server does that part, and every decision about
status codes and headers stays in rest.py.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .rest import OrdersAPI, Request

NO_BODY = {204, 304}  # these statuses never carry a body, so no Content-Length either


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep connections alive between requests
    server: _Server

    def _dispatch(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = {name.lower(): value for name, value in self.headers.items()}
        resp = self.server.api.handle(Request(self.command, self.path, headers, body))
        self.send_response(resp.status)
        for name, value in resp.headers.items():
            self.send_header(name, value)
        if resp.status not in NO_BODY:
            self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if resp.status not in NO_BODY:
            self.wfile.write(resp.body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _dispatch

    def log_message(self, *args: object) -> None:
        pass  # keep the demo output clean


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    api: OrdersAPI


@contextmanager
def serve(api: OrdersAPI) -> Iterator[str]:
    """Run `api` on a free localhost port in a background thread; yield its base URL."""
    server = _Server(("127.0.0.1", 0), _Handler)
    server.api = api
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
