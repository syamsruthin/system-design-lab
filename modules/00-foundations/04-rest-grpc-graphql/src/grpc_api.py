"""
The gRPC side: a purpose-built procedure, GetProfileScreen, over HTTP/2.

grpcio handles HTTP/2, framing and connection management. The bytes inside each message are
ours: protowire.py's encode/decode are plugged in as the serializers, where generated
protobuf classes would normally go.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import grpc

from .data import DB
from .protowire import decode_profile, decode_request, encode_profile, encode_request

METHOD = "/shop.Profiles/GetProfileScreen"  # "/<package>.<Service>/<Method>", as in the .proto


def profile_screen(db: DB, user_id: int, limit: int) -> dict:
    """Exactly what the screen needs, assembled server-side in 3 queries."""
    user = db.user(user_id)
    orders = db.orders_of(user_id, limit)
    shipments = db.shipments_for([o["id"] for o in orders])
    return {"name": user["name"], "orders": [{"item": o["item"], "status": s["status"]}
                                             for o, s in zip(orders, shipments)]}


@contextmanager
def serve_grpc(db: DB) -> Iterator[str]:
    """Run the Profiles service on a free localhost port; yield its address."""
    def handle(request: dict, context: grpc.ServicerContext) -> dict:
        return profile_screen(db, request["user_id"], request["limit"])

    method = grpc.unary_unary_rpc_method_handler(handle, request_deserializer=decode_request,
                                                 response_serializer=encode_profile)
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("shop.Profiles",
                                                                          {"GetProfileScreen": method}),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        server.stop(grace=None)


def profile_stub(channel: grpc.Channel, on_bytes: Callable[[int], None] = lambda n: None) -> Callable[..., dict]:
    """A client-side callable for GetProfileScreen. `on_bytes` sees each response's size on the wire."""
    def deserialize(buf: bytes) -> dict:
        on_bytes(len(buf))
        return decode_profile(buf)

    return channel.unary_unary(METHOD, request_serializer=encode_request, response_deserializer=deserialize)
