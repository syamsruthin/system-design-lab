"""
A tiny HTTP/1.1 client on a raw socket that times each phase of a request:

    DNS lookup → TCP connect → TLS handshake → send request → wait for first byte → read response

It keeps the connection open for the next request to the same host (keep-alive), so a
second request skips the first three phases.
"""
from __future__ import annotations

import io
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .http11 import encode, read_message

# Built once: creating a context loads every trusted CA certificate, far too slow to repeat
# for each connection.
TLS_CONTEXT = ssl.create_default_context()


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    request: bytes             # the exact bytes we sent
    raw: bytes                 # the exact bytes we received
    timings: dict[str, float]  # seconds per phase, in order. Phases that didn't happen are absent.
    new_connection: bool

    @property
    def total(self) -> float:
        return sum(self.timings.values())


class TinyHTTPClient:
    """Keeps at most one open connection: the smallest possible connection pool."""

    def __init__(self, keep_alive: bool = True, timeout: float = 5.0, nodelay: bool = True):
        self.keep_alive = keep_alive
        self.timeout = timeout  # give up instead of waiting forever on a stuck server
        self.nodelay = nodelay
        self.connections_opened = 0
        self.tls_version: str | None = None
        self._sock: socket.socket | None = None
        self._stream: io.BufferedReader | None = None
        self._origin: tuple[str, str, int] | None = None  # (scheme, host, port) of the open connection

    def __enter__(self) -> TinyHTTPClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str) -> Response:
        parts = urlsplit(url)
        scheme, host = parts.scheme, parts.hostname or ""
        port = parts.port or (443 if scheme == "https" else 80)
        timings: dict[str, float] = {}
        new_connection = self._origin != (scheme, host, port)
        try:
            if new_connection:
                self.close()
                self._connect(scheme, host, port, timings)
            assert self._sock and self._stream
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            request = encode(f"GET {target} HTTP/1.1", {
                "Host": parts.netloc,
                "User-Agent": "tiny-client/0.1",
                "Connection": "keep-alive" if self.keep_alive else "close",
            })
            clock = time.perf_counter()
            self._sock.sendall(request)
            clock = lap(timings, "send", clock)
            self._stream.peek(1)  # blocks until the first byte of the answer arrives
            clock = lap(timings, "wait", clock)
            message = read_message(self._stream)
            lap(timings, "read", clock)
        except BaseException:
            # A timed-out request may still be answered later. Reusing this connection would
            # read that late answer as the response to the NEXT request, so throw it away.
            self.close()
            raise
        if message is None:
            self.close()
            raise ConnectionError("server closed the connection without answering")
        if not self.keep_alive or message.headers.get("connection", "").lower() == "close":
            self.close()
        status = int(message.start_line.split(" ")[1])
        return Response(status, message.headers, message.body, request, message.raw, timings, new_connection)

    def _connect(self, scheme: str, host: str, port: int, timings: dict[str, float]) -> None:
        clock = time.perf_counter()
        # 1. DNS: name → IP address. IPv4 only, because "localhost" can resolve to ::1 first
        #    while our servers listen on 127.0.0.1.
        family, kind, proto, _, address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0]
        clock = lap(timings, "dns", clock)
        # 2. TCP: SYN → SYN-ACK → ACK. connect() returns after one round trip.
        sock = socket.socket(family, kind, proto)
        sock.settimeout(self.timeout)
        if self.nodelay:
            # Send small writes at once. Nagle's algorithm would hold our first request back
            # until the server ACKs the TLS handshake's last message, and servers delay ACKs
            # (~40 ms on Linux). curl, httpx and Python's http.client all set this option too.
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.connect(address)
        clock = lap(timings, "connect", clock)
        # 3. TLS (https only): check the server's certificate and agree on encryption keys.
        #    TLS 1.3 needs one more round trip, TLS 1.2 two.
        if scheme == "https":
            sock = TLS_CONTEXT.wrap_socket(sock, server_hostname=host)
            self.tls_version = sock.version()
            lap(timings, "tls", clock)
        self._sock, self._stream = sock, sock.makefile("rb")
        self._origin = (scheme, host, port)
        self.connections_opened += 1

    def close(self) -> None:
        if self._stream:
            self._stream.close()
        if self._sock:
            self._sock.close()
        self._sock, self._stream, self._origin = None, None, None


def lap(timings: dict[str, float], phase: str, since: float) -> float:
    now = time.perf_counter()
    timings[phase] = now - since
    return now
