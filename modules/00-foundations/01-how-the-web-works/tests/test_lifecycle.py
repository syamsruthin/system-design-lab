"""Tests that pin down how a request travels from client to server and back."""
import json
import threading
import time

import httpx
import pytest

from src.client import TinyHTTPClient
from src.fastapi_app import app, run_uvicorn
from src.server import TinyHTTPServer


def test_request_is_plain_text_and_response_says_where_it_ends():
    with TinyHTTPServer(work_ms=0) as server, TinyHTTPClient() as client:
        r = client.get(f"http://localhost:{server.port}/users/42")
    assert r.request.startswith(b"GET /users/42 HTTP/1.1\r\nHost: localhost:")
    assert r.request.endswith(b"\r\n\r\n")  # blank line = end of headers; a GET has no body
    assert r.raw.startswith(b"HTTP/1.1 200 OK\r\n")
    assert int(r.headers["content-length"]) == len(r.body)  # framing: the client knows where to stop
    assert json.loads(r.body) == {"id": 42, "name": "user-42"}


def test_server_routes_unknown_paths_to_404():
    with TinyHTTPServer(work_ms=0) as server, TinyHTTPClient() as client:
        assert client.get(f"http://127.0.0.1:{server.port}/nope").status == 404


def test_real_world_client_and_server_speak_the_same_protocol():
    with TinyHTTPServer(work_ms=0) as server:
        assert httpx.get(f"http://127.0.0.1:{server.port}/users/7").json() == {"id": 7, "name": "user-7"}
    with run_uvicorn() as port, TinyHTTPClient() as client:
        r = client.get(f"http://127.0.0.1:{port}/users/7")
    assert r.status == 200 and json.loads(r.body) == {"id": 7, "name": "user-7"}
    assert r.headers["server"] == "uvicorn"


def test_keep_alive_carries_many_requests_over_one_connection():
    with TinyHTTPServer(work_ms=0) as server:
        for keep_alive, expected_connections in ((True, 1), (False, 10)):
            before = server.connections
            with TinyHTTPClient(keep_alive=keep_alive) as client:
                for i in range(10):
                    assert client.get(f"http://127.0.0.1:{server.port}/users/{i}").status == 200
            assert client.connections_opened == expected_connections
            assert server.connections - before == expected_connections
    assert len(server.log) == 20  # every request was served either way


def test_reused_connection_skips_dns_and_tcp_handshake():
    with TinyHTTPServer(work_ms=0) as server, TinyHTTPClient() as client:
        first = client.get(f"http://localhost:{server.port}/users/1")
        second = client.get(f"http://localhost:{server.port}/users/2")
    assert list(first.timings) == ["dns", "connect", "send", "wait", "read"]  # the lifecycle, in order
    assert list(second.timings) == ["send", "wait", "read"]
    assert first.new_connection and not second.new_connection


def test_time_to_first_byte_includes_the_servers_work():
    with TinyHTTPServer(work_ms=50) as server, TinyHTTPClient() as client:
        r = client.get(f"http://127.0.0.1:{server.port}/users/1")
    assert r.timings["wait"] >= 0.050  # the client waits while the server queries its "database"
    assert server.log[0].handler_ms >= 50


def test_httpx_client_pools_connections_but_httpx_get_does_not():
    ports: list[int] = app.state.client_ports
    with run_uvicorn() as port:
        url = f"http://127.0.0.1:{port}/users/1"
        ports.clear()
        for _ in range(5):
            httpx.get(url)  # a throwaway client per call
        assert len(set(ports)) == 5  # five client ports = five TCP connections
        ports.clear()
        with httpx.Client() as client:
            for _ in range(5):
                client.get(url)
        assert len(set(ports)) == 1


def concurrent_latencies(threaded: bool, clients: int = 4, work_ms: int = 50) -> list[float]:
    latencies: list[float] = []
    with TinyHTTPServer(work_ms=work_ms, threaded=threaded) as server:

        def call() -> None:
            with TinyHTTPClient(keep_alive=False) as client:
                latencies.append(client.get(f"http://127.0.0.1:{server.port}/users/1").total)

        threads = [threading.Thread(target=call) for _ in range(clients)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    return sorted(latencies)


def test_threaded_server_serves_concurrent_clients_in_parallel():
    assert max(concurrent_latencies(threaded=True)) < 0.050 * 2


def test_one_at_a_time_server_makes_concurrent_clients_queue():
    latencies = concurrent_latencies(threaded=False)
    # The k-th client waits for the k-1 ahead of it: roughly 50, 100, 150, 200 ms.
    for k, latency in enumerate(latencies, 1):
        assert latency >= 0.050 * k * 0.9


def test_timeout_gives_up_and_never_reuses_the_poisoned_connection():
    with TinyHTTPServer(work_ms=300) as server, TinyHTTPClient(timeout=0.1) as client:
        start = time.perf_counter()
        with pytest.raises(TimeoutError):
            client.get(f"http://127.0.0.1:{server.port}/users/1")
        assert time.perf_counter() - start < 0.25  # gave up at the timeout, not after 300 ms
        time.sleep(0.3)  # by now the server has sent its late 200 for /users/1 ...
        r = client.get(f"http://127.0.0.1:{server.port}/nope")
    assert r.status == 404  # ... yet we read the right answer, because we used a fresh connection
    assert client.connections_opened == 2
