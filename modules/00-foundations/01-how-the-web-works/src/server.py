"""
A tiny HTTP/1.1 server on a raw TCP socket, so the server's half of the request
lifecycle is visible:

    listen → accept a connection → read request → route → handler → write response
                                   └──── repeats while the client keeps the connection alive

threaded=True gives each connection its own thread. threaded=False serves one
connection at a time (Break it uses that to show why servers need concurrency).
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus

from .http11 import encode, read_message


@dataclass
class LogLine:
    connection: int    # which TCP connection carried the request: 1, 2, 3, ...
    client: str        # "ip:port". The client's OS picks a new (ephemeral) port per connection.
    request_line: str
    status: int
    handler_ms: float


class TinyHTTPServer:
    def __init__(self, work_ms: float = 20, threaded: bool = True, keep_alive_s: float = 5.0):
        # socket() + bind() + listen(). From here on, the kernel completes TCP handshakes
        # by itself and queues finished connections until the app calls accept().
        self._listener = socket.create_server(("127.0.0.1", 0))  # port 0: the OS picks a free one
        self.port: int = self._listener.getsockname()[1]
        self.work_ms = work_ms            # each request pretends to run a database query this long
        self.threaded = threaded
        self.keep_alive_s = keep_alive_s  # close a connection that sends nothing for this long
        self.connections = 0              # TCP connections accepted so far
        self.log: list[LogLine] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)

    def __enter__(self) -> TinyHTTPServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._listener.close()

    def _accept_loop(self) -> None:
        self._listener.settimeout(0.05)  # wake up regularly to notice _stop
        while not self._stop.is_set():
            try:
                conn, (ip, port) = self._listener.accept()
            except TimeoutError:
                continue
            self.connections += 1
            args = (conn, f"{ip}:{port}", self.connections)
            if self.threaded:
                threading.Thread(target=self._serve, args=args, daemon=True).start()
            else:
                self._serve(*args)  # nobody else gets accepted until this connection closes

    def _serve(self, conn: socket.socket, client: str, connection: int) -> None:
        conn.settimeout(self.keep_alive_s)
        with conn, conn.makefile("rb") as stream:
            try:
                while (request := read_message(stream)) is not None:
                    start = time.perf_counter()
                    status, body = self.handle(request.start_line)
                    handler_ms = (time.perf_counter() - start) * 1000
                    self.log.append(LogLine(connection, client, request.start_line, status, handler_ms))
                    # HTTP/1.1 keeps the connection open unless the client says otherwise.
                    keep_alive = request.headers.get("connection", "").lower() != "close"
                    conn.sendall(encode(f"HTTP/1.1 {status} {HTTPStatus(status).phrase}", {
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),  # tells the client where this response ends
                        "Connection": "keep-alive" if keep_alive else "close",
                    }, body))
                    if not keep_alive:
                        break
            except (TimeoutError, ConnectionError):
                pass  # idle for keep_alive_s, or the client went away: close the connection

    def handle(self, request_line: str) -> tuple[int, bytes]:
        """Routing plus the application's work. Everything else in this file is plumbing."""
        try:
            method, target, _version = request_line.split(" ")
        except ValueError:
            return 400, b'{"error": "malformed request line"}'
        if method == "GET" and (match := re.fullmatch(r"/users/(\d+)", target)):
            time.sleep(self.work_ms / 1000)  # stands in for a database query
            return 200, json.dumps({"id": int(match[1]), "name": f"user-{match[1]}"}).encode()
        return 404, b'{"error": "not found"}'
