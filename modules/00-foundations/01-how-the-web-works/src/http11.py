r"""
HTTP/1.1 on the wire. A message is a few lines of text, then an optional body:

    GET /users/42 HTTP/1.1\r\n        start line (a request's is: method, target, version)
    Host: localhost:8080\r\n          headers, one "Name: value" per line
    \r\n                              blank line = end of headers
    <body>                            exactly Content-Length bytes (our GET requests have none)

Requests and responses share this format, so the server and the client both use
read_message() below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO


@dataclass
class Message:
    start_line: str          # "GET /users/42 HTTP/1.1" or "HTTP/1.1 200 OK"
    headers: dict[str, str]  # names lower-cased, because HTTP header names are case-insensitive
    body: bytes
    raw: bytes               # every byte of this message exactly as it crossed the wire


def encode(start_line: str, headers: dict[str, str], body: bytes = b"") -> bytes:
    lines = [start_line, *(f"{name}: {value}" for name, value in headers.items())]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def read_message(stream: BinaryIO) -> Message | None:
    """Read one message from a connection, or return None if the peer closed it.

    TCP delivers a stream of bytes with no boundaries, so HTTP has to mark where each
    message ends: the headers end at a blank line, and the body ends after
    Content-Length bytes (or at a zero-size chunk). Without that, one connection
    could not carry a second request.
    """
    raw: list[bytes] = []

    def line() -> bytes:
        raw.append(stream.readline())
        return raw[-1]

    start = line()
    if not start:
        return None  # closed between messages: the normal end of a kept-alive connection
    headers: dict[str, str] = {}
    while (header := line()).strip():
        name, _, value = header.decode("latin-1").partition(":")
        headers[name.strip().lower()] = value.strip()

    if headers.get("transfer-encoding", "").lower() == "chunked":
        # The sender didn't know the length up front (it was streaming), so the body comes
        # in pieces: "<size in hex>\r\n<data>\r\n" ... and finally "0\r\n\r\n".
        body = b""
        while size := int(line().split(b";")[0], 16):
            raw.append(stream.read(size + 2))  # the chunk's data plus its trailing \r\n
            body += raw[-1][:-2]
        while line().strip():  # optional trailer headers, then a blank line
            pass
    else:
        raw.append(stream.read(int(headers.get("content-length", 0))))
        body = raw[-1]
    return Message(start.decode("latin-1").rstrip("\r\n"), headers, body, b"".join(raw))
