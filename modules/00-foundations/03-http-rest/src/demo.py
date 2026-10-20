"""
HTTP, REST & status codes: three experiments that make the rules visible.

    make run                     # all three
    DROP=0.6 make run            # Break it: a worse network, more lost responses
    PRECONDITIONS=off make run   # Break it: the server ignores If-Match
"""
from __future__ import annotations

import json
import os
from http import HTTPStatus

import httpx

from .fastapi_app import build_app, run_uvicorn
from .lossy import LossyTransport, send_with_retries
from .rest import OrdersAPI
from .server import serve

DROP = float(os.environ.get("DROP", 0.3))
CHECK_PRECONDITIONS = os.environ.get("PRECONDITIONS", "on") != "off"

# A conversation with the orders API: (method, path, body, headers). Bytes are sent raw, dicts as JSON.
SCRIPT: list[tuple[str, str, dict | bytes | None, dict[str, str]]] = [
    ("POST", "/orders", {"item": "book", "qty": 1}, {}),
    ("GET", "/orders/1", None, {}),
    ("GET", "/orders/1", None, {"If-None-Match": '"v1"'}),
    ("PUT", "/orders/1", {"item": "book", "qty": 2}, {"If-Match": '"v1"'}),
    ("PUT", "/orders/1", {"item": "book", "qty": 3}, {"If-Match": '"v1"'}),
    ("PATCH", "/orders/1", {"qty": 4}, {}),
    ("POST", "/orders", b"{oops", {}),
    ("POST", "/orders", {"item": "pen", "qty": 0}, {}),
    ("GET", "/orders/99", None, {}),
    ("DELETE", "/orders/1", None, {}),
    ("DELETE", "/orders/1", None, {}),
]
SHOWN_HEADERS = ("Location", "ETag", "Allow")


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def send(client: httpx.Client, method: str, path: str, body: dict | bytes | None, headers: dict) -> httpx.Response:
    if isinstance(body, bytes):
        return client.request(method, path, content=body, headers={"Content-Type": "application/json", **headers})
    return client.request(method, path, json=body, headers=headers)


def describe(method: str, path: str, body: dict | bytes | None, headers: dict) -> str:
    text = f"{method} {path}"
    if body is not None:
        text += " " + (body.decode() if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")))
    return text + "".join(f"  [{k}: {v}]" for k, v in headers.items())


def experiment_conversation() -> None:
    print("\n1) A REST conversation: the status code says what happened and what to do next")
    results: dict[str, list[httpx.Response]] = {}
    with serve(OrdersAPI()) as ours, run_uvicorn(build_app()) as theirs:
        for name, base in (("ours", ours), ("fastapi", theirs)):
            with httpx.Client(base_url=base) as client:
                results[name] = [send(client, *step) for step in SCRIPT]
    rows = []
    for step, mine, fast in zip(SCRIPT, results["ours"], results["fastapi"]):
        shown = ", ".join(f"{h}: {mine.headers[h]}" for h in SHOWN_HEADERS if h in mine.headers)
        same = "" if fast.status_code == mine.status_code else "  ← differs"
        rows.append([describe(*step), f"{mine.status_code} {HTTPStatus(mine.status_code).phrase}", shown,
                     f"{fast.status_code}{same}"])
    table(["request", "our server", "headers that matter", "FastAPI"], rows)
    print("  → 2xx: it worked. 3xx: use what you have, or look elsewhere. 4xx: fix the request. 5xx: the server failed.")


def experiment_retries(n: int = 100) -> None:
    print(f"\n2) Retrying over a lossy network: {n} orders, {DROP:.0%} of responses lost, the client retries")
    rows = []
    for method in ("POST", "PUT"):
        api = OrdersAPI()
        transport = LossyTransport(DROP, seed=42)  # same seed: the same responses get lost for both methods
        with serve(api) as base, httpx.Client(transport=transport, base_url=base) as client:
            for i in range(n):
                url = "/orders" if method == "POST" else f"/orders/op-{i:03d}"  # PUT: the client names the order
                send_with_retries(client, method, url, {"item": f"item-{i}", "qty": 1})
        rows.append([f"{method} {'/orders' if method == 'POST' else '/orders/{client-chosen id}'}", str(n),
                     str(transport.sent), str(len(api.orders)), str(len(api.orders) - n)])
    table(["method", "orders meant", "requests that reached the server", "orders stored", "duplicates"], rows)
    print("  → a lost response looks like a lost request, so clients retry. POST isn't idempotent: every retry")
    print("    that follows a lost response creates another order. PUT to a named URI just rewrites the same one.")


def experiment_etags(polls: int = 8, change_after: int = 4) -> None:
    print(f"\n3) ETags, part 1: polling an order {polls} times with If-None-Match (it changes after poll {change_after})")
    api = OrdersAPI()
    statuses, downloaded = [], 0
    with serve(api) as base, httpx.Client(base_url=base) as client:
        client.put("/orders/7", json={"item": "lamp", "qty": 1})
        etag = None
        for poll in range(1, polls + 1):
            if poll == change_after + 1:
                client.put("/orders/7", json={"item": "lamp", "qty": 2})  # someone else edits it
                statuses.append("|edit|")
            r = client.get("/orders/7", headers={"If-None-Match": etag} if etag else {})
            statuses.append(str(r.status_code))
            downloaded += len(r.content)
            etag = r.headers["ETag"]
        full_size = len(client.get("/orders/7").content)
    print(f"  statuses: {' '.join(statuses)}")
    print(f"  body bytes downloaded: {downloaded} (without ETags: {polls} × {full_size} = {polls * full_size})")
    print("  → 304 Not Modified means \"the copy you have is current\": the body is skipped, only headers travel.")

    mode = "the server checks If-Match" if CHECK_PRECONDITIONS else "the server IGNORES If-Match"
    print(f"\n   ETags, part 2: Alice and Bob edit the same order at once ({mode})")
    rows = []
    for use_if_match in (False, True):
        api = OrdersAPI(check_preconditions=CHECK_PRECONDITIONS)
        with serve(api) as base, httpx.Client(base_url=base) as alice, httpx.Client(base_url=base) as bob:
            alice.put("/orders/42", json={"item": "pen", "qty": 1})
            seen_a, seen_b = alice.get("/orders/42"), bob.get("/orders/42")  # both read version 1
            cond = (lambda r: {"If-Match": r.headers["ETag"]}) if use_if_match else (lambda r: {})
            a = alice.put("/orders/42", json={"item": "pen", "qty": 5}, headers=cond(seen_a))  # Alice: qty 1 → 5
            b = bob.put("/orders/42", json={"item": "pencil", "qty": 1}, headers=cond(seen_b))  # Bob: pen → pencil
            retry = "—"
            if b.status_code == 412:  # Bob re-reads, re-applies his edit to the fresh copy, tries again
                fresh = bob.get("/orders/42")
                again = bob.put("/orders/42", json={"item": "pencil", "qty": fresh.json()["qty"]}, headers=cond(fresh))
                retry = f"{again.status_code} after re-reading"
            final = bob.get("/orders/42").json()
        kept = "kept" if final["qty"] == 5 else "LOST"
        rows.append(["with If-Match" if use_if_match else "no If-Match", str(a.status_code), str(b.status_code),
                     retry, f'{final["item"]} × {final["qty"]}', kept])
    table(["clients send", "Alice's PUT", "Bob's PUT", "Bob's retry", "final order", "Alice's qty change"], rows)
    print("  → without a precondition, the last writer silently wins. 412 turns that into an error Bob can handle.")


if __name__ == "__main__":
    print("=" * 78)
    print(" HTTP, REST & status codes: the conversation, retries, ETags")
    print("=" * 78)
    experiment_conversation()
    experiment_retries()
    experiment_etags()
