"""
Client-server & the request lifecycle: four experiments that make it visible.

    make run                              # section 2 fetches https://example.com/ (needs internet)
    SEQUENTIAL=1 make run                 # Break it: the server handles one connection at a time
    URL=https://ftp.funet.fi/ make run    # Break it: section 2 against a server much farther away
    NAGLE=1 make run                      # Break it: section 2 without TCP_NODELAY
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from statistics import median

import httpx

from .client import Response, TinyHTTPClient
from .fastapi_app import app, run_uvicorn
from .server import TinyHTTPServer

URL = os.environ.get("URL", "https://example.com/")
SEQUENTIAL = os.environ.get("SEQUENTIAL") == "1"
NAGLE = os.environ.get("NAGLE") == "1"
PHASES = {"dns": "DNS lookup", "connect": "TCP connect", "tls": "TLS handshake",
          "send": "send request", "wait": "wait for first byte", "read": "read response"}


def ms(seconds: float) -> str:
    return f"{seconds * 1000:6.1f} ms"


def timed(work: Callable[[], object]) -> float:
    start = time.perf_counter()
    work()
    return time.perf_counter() - start


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def show_bytes(raw: bytes) -> None:
    """Print a message with its line endings visible: every HTTP line ends in \\r\\n."""
    for text in raw.decode("latin-1").splitlines(keepends=True):
        print("    │ " + text.replace("\r\n", r"\r\n"))


def experiment_raw_http() -> None:
    print("\n1) HTTP is plain text over a TCP connection: one request, byte for byte")
    with TinyHTTPServer(work_ms=20) as server, TinyHTTPClient(keep_alive=False) as client:
        r = client.get(f"http://localhost:{server.port}/users/42")
        print(f"  client → server ({len(r.request)} bytes)")
        show_bytes(r.request)
        print(f"  server → client ({len(r.raw)} bytes)")
        show_bytes(r.raw)
        entry = server.log[-1]
        print(f"  server log : connection #{entry.connection} from {entry.client}, "
              f'"{entry.request_line}" → {entry.status}, handler took {entry.handler_ms:.1f} ms')
        print("  client view: " + ", ".join(f"{PHASES[p]} {ms(t).strip()}" for p, t in r.timings.items()))
        via_httpx = httpx.get(f"http://127.0.0.1:{server.port}/users/7")
    with run_uvicorn() as port, TinyHTTPClient() as client:
        via_tiny = client.get(f"http://127.0.0.1:{port}/users/7")
    print("\n  Different code, same protocol:")
    table(["client", "server", "status", "body"], [
        [f"httpx {httpx.__version__}", "our tiny server", str(via_httpx.status_code), via_httpx.text],
        ["our tiny client", f"FastAPI on {via_tiny.headers['server']}", str(via_tiny.status), via_tiny.body.decode()],
    ])
    print("  → a request is a start line, headers and a blank line; Content-Length says where the body ends.")


def experiment_live(rounds: int = 5) -> None:
    nagle = ", Nagle's algorithm ON" if NAGLE else ""
    print(f"\n2) Over the real internet: GET {URL} twice per connection{nagle} (median of {rounds} connections)")
    firsts: list[Response] = []
    seconds: list[Response] = []
    try:
        for _ in range(rounds):
            with TinyHTTPClient(nodelay=not NAGLE) as client:
                firsts.append(client.get(URL))
                seconds.append(client.get(URL))
                tls = client.tls_version
    except OSError as err:  # offline, DNS failure, firewall, timeout
        print(f"  skipped (no network?): {err!r}")
        return

    def cell(responses: list[Response], phase: str) -> str:
        values = [r.timings[phase] for r in responses if phase in r.timings]
        return ms(median(values)) if values else "     —"

    reused = not any(r.new_connection for r in seconds)
    table(["phase", "request 1: new connection", "request 2: " + ("reused connection" if reused else "NEW connection")],
          [[PHASES[p], cell(firsts, p), cell(seconds, p)] for p in PHASES]
          + [["total", ms(median(r.total for r in firsts)), ms(median(r.total for r in seconds))]])
    rtt = median(r.timings["connect"] for r in firsts)  # connect() returns after one round trip
    setup = median(sum(r.timings.get(p, 0.0) for p in ("dns", "connect", "tls")) for r in firsts)
    first = firsts[0]
    print(f"  HTTP {first.status}, {len(first.body):,}-byte body, {tls or 'no TLS'}, server: {first.headers.get('server', '?')}. "
          f"One round trip (TCP connect) ≈ {rtt * 1000:.1f} ms.")
    if reused:
        print(f"  → request 1 spent {setup * 1000:.1f} ms on DNS + TCP + TLS before it could even be sent; "
              "request 2 skipped all three.")
    else:
        print("  → the server closed the connection after request 1, so request 2 paid for a new one.")


def experiment_keep_alive(n: int = 20) -> None:
    print(f"\n3) Keep-alive on localhost: {n} requests, a new connection each time vs one reused connection")
    rows = []
    with TinyHTTPServer(work_ms=0) as server:
        url = f"http://127.0.0.1:{server.port}/users/1"
        for keep_alive in (False, True):
            before = server.connections
            with TinyHTTPClient(keep_alive=keep_alive) as tiny:
                took = timed(lambda: [tiny.get(url) for _ in range(n)])
            label = "tiny client, keep-alive" if keep_alive else "tiny client, Connection: close"
            rows.append([f"{label} → tiny server", str(server.connections - before), ms(took), ms(took / n)])

    ports: list[int] = app.state.client_ports  # one distinct client port = one TCP connection
    with run_uvicorn() as port:
        url = f"http://127.0.0.1:{port}/users/1"
        ports.clear()
        took = timed(lambda: [httpx.get(url) for _ in range(n)])  # each call builds a throwaway client
        rows.append(["httpx.get() in a loop → FastAPI", str(len(set(ports))), ms(took), ms(took / n)])
        ports.clear()
        with httpx.Client() as pooled:  # one client = one connection pool, reused by every call
            took = timed(lambda: [pooled.get(url) for _ in range(n)])
        rows.append(["one httpx.Client() → FastAPI", str(len(set(ports))), ms(took), ms(took / n)])
    table(["client → server", "TCP connections the server saw", "total", "per request"], rows)
    print("  → keep-alive turns N connections into 1. A handshake is cheap on localhost; section 2 shows its real price.")


def experiment_concurrency(clients: int = 5, work_ms: int = 100) -> None:
    mode = "ONE connection at a time" if SEQUENTIAL else "a thread per connection"
    print(f"\n4) {clients} clients arrive at once, each request needs {work_ms} ms of server work (server: {mode})")
    results: list[Response] = []
    with TinyHTTPServer(work_ms=work_ms, threaded=not SEQUENTIAL) as server:

        def one_client(i: int) -> None:
            with TinyHTTPClient(keep_alive=False) as client:
                results.append(client.get(f"http://127.0.0.1:{server.port}/users/{i}"))

        threads = [threading.Thread(target=one_client, args=(i,)) for i in range(clients)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    rows = [[f"#{i}", ms(r.timings["connect"]), ms(r.timings["wait"]), ms(r.total)]
            for i, r in enumerate(sorted(results, key=lambda r: r.total), 1)]
    table(["client (by finish)", "TCP connect", "wait for first byte", "total"], rows)
    if SEQUENTIAL:
        print("  → connect is still instant, because the kernel finishes the handshake and queues the connection.")
        print("    But each request sits unread until the server has finished everyone ahead of it.")
    else:
        print(f"  → each connection gets its own thread, so all {clients} finish in ≈{work_ms} ms. "
              "Break it: SEQUENTIAL=1 make run")


if __name__ == "__main__":
    print("=" * 78)
    print(" Client-server & the request lifecycle: raw HTTP, phases, keep-alive, concurrency")
    print("=" * 78)
    experiment_raw_http()
    experiment_live()
    experiment_keep_alive()
    experiment_concurrency()
