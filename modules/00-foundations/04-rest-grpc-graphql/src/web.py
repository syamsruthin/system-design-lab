"""
REST and GraphQL over the same data, on one FastAPI app (GraphQL is mounted at /graphql).

The REST side is resource-shaped, as in the previous lesson: each endpoint returns a whole
resource, and the client composes a screen from several of them.
"""
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from .data import DB
from .graphql_api import make_context, schema


def build_app(db: DB, batched: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/users/{uid}")
    def get_user(uid: int) -> dict:
        return db.user(uid)

    @app.get("/users/{uid}/orders")
    def get_orders(uid: int, limit: int = 3) -> list[dict]:
        return db.orders_of(uid, limit)

    @app.get("/orders/{oid}/shipment")
    def get_shipment(oid: int) -> dict:
        return db.shipment(oid)

    async def context() -> dict:
        return make_context(db, batched)

    app.include_router(GraphQLRouter(schema, context_getter=context), prefix="/graphql")
    return app


@contextmanager
def run_uvicorn(app: FastAPI) -> Iterator[str]:
    """Serve `app` with uvicorn in a background thread on a free port; yield its base URL."""
    listener = socket.create_server(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    while not server.started and thread.is_alive():
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("uvicorn failed to start")
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join()
        listener.close()
