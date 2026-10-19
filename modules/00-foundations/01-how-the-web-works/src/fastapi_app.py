"""
The same endpoint on production software: FastAPI running on the uvicorn server.

It proves our hand-written client speaks real HTTP, and it lets us watch httpx's
connection pool from the server's side. Every TCP connection has its own client
port, so counting the distinct ports the server saw counts the connections.
"""
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()
app.state.client_ports = []  # client port of every request served


@app.get("/users/{user_id}")
async def get_user(user_id: int, request: Request) -> dict[str, int | str]:
    if request.client:
        app.state.client_ports.append(request.client.port)
    return {"id": user_id, "name": f"user-{user_id}"}


@contextmanager
def run_uvicorn() -> Iterator[int]:
    """Serve `app` with uvicorn in a background thread on a free port, and yield the port."""
    listener = socket.create_server(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    while not server.started and thread.is_alive():
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("uvicorn failed to start")
    try:
        yield listener.getsockname()[1]
    finally:
        server.should_exit = True
        thread.join()
        listener.close()
