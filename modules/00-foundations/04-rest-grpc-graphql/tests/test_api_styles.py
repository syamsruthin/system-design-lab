"""Tests that pin down what distinguishes REST, gRPC and GraphQL."""
import asyncio
import json

import grpc
import httpx

from src.data import make_db
from src.demo import FIELDS_USED, friends_query, leaves, rest_screen
from src.graphql_api import make_context, schema
from src.grpc_api import profile_screen, profile_stub, serve_grpc
from src.protowire import (decode_fields, decode_profile, decode_varint, encode_field, encode_profile,
                           encode_varint)
from src.web import build_app, run_uvicorn

SCREEN_QUERY = "{ user(id: 1) { name orders(limit: 3) { item shipment { status } } } }"


def gql(query: str, batched: bool = True) -> tuple[dict, int]:
    db = make_db()
    result = asyncio.run(schema.execute(query, context_value=make_context(db, batched)))
    assert result.errors is None
    return result.data, db.queries


def test_varints_match_the_protobuf_spec():
    assert encode_field(1, 150) == bytes([0x08, 0x96, 0x01])  # the example in the protobuf encoding docs
    for n in (0, 1, 127, 128, 300, 2**31, 2**63 - 1):
        assert decode_varint(encode_varint(n), 0) == (n, len(encode_varint(n)))
    assert len(encode_varint(127)) == 1 and len(encode_varint(128)) == 2  # 7 payload bits per byte


def test_protobuf_round_trips_and_is_smaller_than_json():
    screen = profile_screen(make_db(), user_id=1, limit=3)
    wire = encode_profile(screen)
    assert decode_profile(wire) == screen
    assert len(wire) < len(json.dumps(screen, separators=(",", ":"))) * 0.6  # no names, no quotes, no braces


def test_unknown_fields_are_skipped_so_old_clients_survive_schema_changes():
    screen = profile_screen(make_db(), user_id=1, limit=3)
    newer = encode_profile(screen) + encode_field(3, "VIP") + encode_field(4, 42)
    assert [n for n, _ in decode_fields(newer)][-2:] == [3, 4]
    assert decode_profile(newer) == screen


def test_graphql_returns_exactly_the_requested_fields():
    data, _ = gql(SCREEN_QUERY)
    assert leaves(data) == FIELDS_USED
    assert set(data["user"]) == {"name", "orders"}  # no email, phone, address...
    assert set(data["user"]["orders"][0]) == {"item", "shipment"}


def test_rest_needs_more_requests_and_bytes_than_graphql_and_grpc():
    db = make_db()
    with run_uvicorn(build_app(db)) as base, httpx.Client(base_url=base) as client:
        rest_requests, rest_bytes, rest_fields = rest_screen(client)
        graphql_bytes = len(client.post("/graphql", json={"query": SCREEN_QUERY}).content)
    with serve_grpc(db) as target, grpc.insecure_channel(target) as channel:
        sizes: list[int] = []
        screen = profile_stub(channel, sizes.append)({"user_id": 1, "limit": 3})
    assert rest_requests == 5 and rest_fields > 5 * FIELDS_USED  # over-fetching
    assert sizes[0] < graphql_bytes < rest_bytes  # protobuf < GraphQL's JSON < whole resources
    assert screen["name"] == "user-1" and len(screen["orders"]) == 3


def test_naive_resolvers_cause_n_plus_one_and_dataloader_batches_them():
    query = f"{{ users(ids: {list(range(1, 21))}) {{ name orders {{ item shipment {{ status }} }} }} }}"
    naive_data, naive_queries = gql(query, batched=False)
    batched_data, batched_queries = gql(query, batched=True)
    assert naive_data == batched_data  # same answer...
    assert naive_queries == 1 + 20 + 20 * 3  # 1 for users, 1 per user, 1 per order
    assert batched_queries == 3  # ...one query per level instead


def test_nested_queries_grow_exponentially_while_batched_db_queries_grow_linearly():
    sizes = [gql(friends_query(d)) for d in (1, 2, 3)]
    users = [leaves(data) for data, _ in sizes]
    assert users == [1 + 5, 1 + 5 + 25, 1 + 5 + 25 + 125]
    assert [queries for _, queries in sizes] == [3, 5, 7]  # 1 + 2 per level
