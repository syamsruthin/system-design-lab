"""
REST vs gRPC vs GraphQL: the same profile screen, built three ways.

    make run               # all four experiments
    RTT=300 make run       # section 2's latency estimate for a slower network
    DEPTH=6 make run       # Break it: a deeply nested GraphQL query
"""
from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor

import grpc
import httpx

from .data import make_db
from .graphql_api import make_context, schema
from .grpc_api import profile_screen, profile_stub, serve_grpc
from .protowire import decode_profile, encode_field, encode_profile
from .web import build_app, run_uvicorn

RTT_MS = int(os.environ.get("RTT", 100))
DEPTH = int(os.environ.get("DEPTH", 3))
SCREEN_QUERY = "{ user(id: 1) { name orders(limit: 3) { item shipment { status } } } }"
FIELDS_USED = 7  # the screen shows: the user's name, and item + status for 3 orders


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def leaves(value: object) -> int:
    """How many scalar fields a JSON-like value contains."""
    if isinstance(value, dict):
        return sum(leaves(v) for v in value.values())
    if isinstance(value, list):
        return sum(leaves(v) for v in value)
    return 1


def experiment_encoding() -> None:
    print("\n1) The same data, two encodings: JSON (text, with names) vs protobuf (binary, numbered fields)")
    screen = profile_screen(make_db(), user_id=1, limit=3)
    as_json, as_proto = json.dumps(screen, separators=(",", ":")).encode(), encode_profile(screen)
    print(f"  JSON     {len(as_json):3} bytes  {as_json.decode()}")
    print(f"  protobuf {len(as_proto):3} bytes  {as_proto.hex(' ')}")
    name = encode_field(1, screen["name"])
    print(f"  how the first field reads: {name[:1].hex()} = field 1, wire type 2 (length-delimited) · "
          f"{name[1:2].hex()} = {name[1]} bytes follow · {name[2:].hex(' ')} = {screen['name']!r}")
    print(f"  varints: 150 → {encode_field(1, 150)[1:].hex(' ')} (7 bits per byte, top bit = \"more\"); "
          f"5 → {encode_field(1, 5)[1:].hex()}")
    newer = as_proto + encode_field(3, "VIP")  # a newer server adds field 3, "tier"
    print(f"  an old client reads a newer message with an extra field 3: {decode_profile(newer) == screen} "
          "(unknown fields are skipped)")
    print(f"  → protobuf is {len(as_proto) / len(as_json):.0%} of the JSON size here, and both sides need the schema "
          "to read it.")


def rest_screen(client: httpx.Client) -> tuple[int, int, int]:
    """Build the screen from resources. Stage 1 fetches user and orders in parallel; stage 2 needs the
    order ids first, then fetches every shipment in parallel. Returns (requests, bytes, fields)."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        stage1 = list(pool.map(client.get, ["/users/1", "/users/1/orders?limit=3"]))
        stage2 = list(pool.map(client.get, [f"/orders/{o['id']}/shipment" for o in stage1[1].json()]))
    responses = stage1 + stage2
    return len(responses), sum(len(r.content) for r in responses), sum(leaves(r.json()) for r in responses)


def experiment_styles() -> None:
    print(f"\n2) One profile screen (name + 3 orders with their shipping status), three API styles")
    rows = []
    db = make_db()
    with run_uvicorn(build_app(db)) as base, httpx.Client(base_url=base) as client:
        before = db.queries
        requests, size, fields = rest_screen(client)
        rows.append(["REST (5 resource endpoints)", str(requests), "2", str(size), str(fields), str(db.queries - before)])

        before = db.queries
        r = client.post("/graphql", json={"query": SCREEN_QUERY})
        rows.append(["GraphQL (1 query, POST /graphql)", "1", "1", str(len(r.content)),
                     str(leaves(r.json()["data"])), str(db.queries - before)])

    with serve_grpc(db) as target, grpc.insecure_channel(target) as channel:
        sizes: list[int] = []
        before = db.queries
        screen = profile_stub(channel, sizes.append)({"user_id": 1, "limit": 3})
        rows.append(["gRPC (1 call, GetProfileScreen)", "1", "1", str(sizes[0]), str(leaves(screen)),
                     str(db.queries - before)])
    for row in rows:
        row.append(f"{int(row[2]) * RTT_MS} ms")
    table(["style", "requests", "dependent round trips", "body bytes", f"fields received (used: {FIELDS_USED})",
           "DB queries", f"latency @ {RTT_MS} ms RTT"], rows)
    print("  → REST over-fetches whole resources and needs two dependent round trips; GraphQL and gRPC return")
    print("    just the screen in one. Latency column = dependent round trips × RTT (server time left out).")


def run_query(query: str, batched: bool) -> tuple[dict, int]:
    db = make_db()
    result = asyncio.run(schema.execute(query, context_value=make_context(db, batched)))
    if result.errors:
        raise RuntimeError(result.errors)
    return result.data, db.queries


def experiment_n_plus_one(n_users: int = 20) -> None:
    print(f"\n3) GraphQL's N+1 problem: the same screen for {n_users} users in one query")
    query = f"{{ users(ids: {list(range(1, n_users + 1))}) {{ name orders(limit: 3) {{ item shipment {{ status }} }} }} }}"
    rows = []
    for batched in (False, True):
        data, queries = run_query(query, batched)
        label = "DataLoader (batched resolvers)" if batched else "naive resolvers"
        rows.append([label, str(leaves(data)), str(queries)])
    table(["resolvers", "fields returned", "DB queries"], rows)
    print(f"  → naive: 1 query for the users, then 1 per user for orders, then 1 per order for its shipment.")
    print("    DataLoader collects the calls each level makes and runs one batched query per level.")


def friends_query(depth: int) -> str:
    level = "name"
    for _ in range(depth):
        level = f"name friends {{ {level} }}"
    return f"{{ user(id: 1) {{ {level} }} }}"


def experiment_depth() -> None:
    print(f"\n4) Nested queries multiply: friends of friends of ... (5 friends each, DataLoader on)")
    rows = []
    for depth in range(1, DEPTH + 1):
        data, queries = run_query(friends_query(depth), batched=True)
        rows.append([str(depth), friends_query(depth) if depth <= 2 else "…", f"{leaves(data):,}",
                     f"{len(json.dumps(data)):,}", str(queries)])
    table(["depth", "query", "users in response", "response bytes", "DB queries"], rows)
    print("  → each level multiplies the response by 5. Batching (and DataLoader's per-request cache) keeps DB")
    print("    queries small, but the response and the server's work still grow exponentially with depth.")


if __name__ == "__main__":
    print("=" * 78)
    print(" REST vs gRPC vs GraphQL: encodings, round trips, N+1 and fan-out")
    print("=" * 78)
    experiment_encoding()
    experiment_styles()
    experiment_n_plus_one()
    experiment_depth()
