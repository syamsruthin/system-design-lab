"""
The same orders API on FastAPI, to compare a real framework's answers with ours.

FastAPI handles routing, JSON parsing and validation for us; status codes, ETags and
preconditions are still decisions we write by hand.
"""
from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class Order(BaseModel):
    item: str
    qty: int = Field(ge=1)


def build_app() -> FastAPI:
    app = FastAPI()
    orders: dict[str, dict] = {}
    versions: dict[str, int] = {}
    next_id = [1]

    def etag(oid: str) -> str:
        return f'"v{versions[oid]}"'

    def save(oid: str, order: Order) -> None:
        orders[oid] = order.model_dump()
        versions[oid] = versions.get(oid, 0) + 1

    @app.get("/orders")
    def list_orders() -> list[dict]:
        return [{"id": oid, **o} for oid, o in orders.items()]

    @app.post("/orders", status_code=201)
    def create(order: Order) -> Response:
        oid = str(next_id[0])
        next_id[0] += 1
        save(oid, order)
        return JSONResponse({"id": oid, **orders[oid]}, 201, {"Location": f"/orders/{oid}", "ETag": etag(oid)})

    @app.get("/orders/{oid}")
    def read(oid: str, if_none_match: str | None = Header(None)) -> Response:
        if oid not in orders:
            return JSONResponse({"error": f"order {oid} not found"}, 404)
        if if_none_match == etag(oid):
            return Response(status_code=304, headers={"ETag": etag(oid)})
        return JSONResponse({"id": oid, **orders[oid]}, 200, {"ETag": etag(oid)})

    @app.put("/orders/{oid}")
    def replace(oid: str, order: Order, if_match: str | None = Header(None)) -> Response:
        if if_match is not None and (oid not in orders or if_match not in ("*", etag(oid))):
            return JSONResponse({"error": "precondition failed"}, 412)
        created = oid not in orders
        save(oid, order)
        headers = {"ETag": etag(oid), **({"Location": f"/orders/{oid}"} if created else {})}
        return JSONResponse({"id": oid, **orders[oid]}, 201 if created else 200, headers)

    @app.delete("/orders/{oid}", status_code=204)
    def delete(oid: str) -> Response:
        if oid not in orders:
            return JSONResponse({"error": f"order {oid} not found"}, 404)
        del orders[oid]
        return Response(status_code=204)

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
