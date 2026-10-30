"""
Measure this machine's own "latency numbers every programmer should know".

Each benchmark runs an operation many times and keeps the *best* average of several
rounds: the best run is the closest to the operation's true cost, with the least noise
from other programs. Numbers differ per machine; the gaps between them (factors of
10 to 1,000,000) are what estimates rely on.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
from collections.abc import Callable


def best_per_op(op: Callable[[], object], per_round: int, rounds: int = 5) -> float:
    """Seconds per operation: the best of `rounds` averages of `per_round` calls."""
    best = float("inf")
    for _ in range(rounds):
        start = time.perf_counter()
        for _ in range(per_round):
            op()
        best = min(best, (time.perf_counter() - start) / per_round)
    return best


def dict_lookup() -> float:
    table = {i: i for i in range(100_000)}
    return best_per_op(lambda: table[54_321], 200_000)


def sha256_1mb() -> float:
    data = os.urandom(1_000_000)
    return best_per_op(lambda: hashlib.sha256(data).digest(), 50)


def json_encode_1kb() -> float:
    doc = {"id": 42, "name": "user-42", "tags": ["a", "b", "c"] * 20, "bio": "x" * 600}
    return best_per_op(lambda: json.dumps(doc), 20_000)


def copy_1mb() -> float:
    data = bytearray(1_000_000)
    return best_per_op(lambda: bytes(data), 500)


def localhost_round_trip() -> float:
    """One small message to a local TCP echo server and back: the floor for any network call."""
    server = socket.create_server(("127.0.0.1", 0))

    def echo() -> None:
        conn, _ = server.accept()
        with conn:
            while data := conn.recv(64):
                conn.sendall(data)

    threading.Thread(target=echo, daemon=True).start()
    with socket.create_connection(server.getsockname()) as client:
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def ping() -> None:
            client.sendall(b"x")
            client.recv(64)

        result = best_per_op(ping, 2_000)
    server.close()
    return result


def fsync_4kb(full: bool = False) -> float:
    """Write 4 KB and ask the OS to make it durable: what every database commit pays.

    On macOS, plain fsync() only hands the data to the drive, which may still hold it in its
    own volatile cache. F_FULLFSYNC waits until the drive has really stored it, and that's
    the honest cost of durability (databases on macOS use it)."""
    with tempfile.NamedTemporaryFile() as f:
        def write_and_sync() -> None:
            f.write(b"x" * 4096)
            f.flush()
            if full:
                fcntl.fcntl(f.fileno(), fcntl.F_FULLFSYNC)
            else:
                os.fsync(f.fileno())

        return best_per_op(write_and_sync, 20 if full else 50, rounds=3)


def sequential_read_mb() -> float:
    """Seconds per MB when reading a 64 MB file that the OS has already cached in memory."""
    with tempfile.NamedTemporaryFile() as f:
        f.write(os.urandom(64_000_000))
        f.flush()

        def read_all() -> None:
            f.seek(0)
            while f.read(1 << 20):
                pass

        return best_per_op(read_all, 2, rounds=3) / 64


BENCHMARKS: list[tuple[str, Callable[[], float], str]] = [
    # (operation, benchmark, nearest entry in the classic "latency numbers" table, ~2012 version)
    ("Python dict lookup", dict_lookup, "main memory reference: 100 ns"),
    ("json.dumps of a 1 KB object", json_encode_1kb, "compress 1 KB with Zippy: 3 µs"),
    ("copy 1 MB in memory", copy_1mb, "read 1 MB sequentially from memory: 250 µs"),
    ("read 1 MB of a cached file", sequential_read_mb, "read 1 MB sequentially from memory: 250 µs"),
    ("SHA-256 of 1 MB", sha256_1mb, "—"),
    ("localhost TCP round trip", localhost_round_trip, "round trip within the same datacenter: 500 µs"),
    ("write 4 KB + fsync", fsync_4kb, "read 4 KB randomly from SSD: 150 µs; disk seek: 10 ms"),
]
if hasattr(fcntl, "F_FULLFSYNC"):  # macOS only
    BENCHMARKS.append(("write 4 KB + F_FULLFSYNC (really durable)", lambda: fsync_4kb(full=True), "disk seek: 10 ms"))


def run_all() -> list[tuple[str, float, str]]:
    return [(name, bench(), classic) for name, bench, classic in BENCHMARKS]
