"""Tests that pin down what HTTP's methods and status codes promise."""
import json

import httpx

from src.fastapi_app import build_app, run_uvicorn
from src.lossy import LossyTransport, send_with_retries
from src.rest import OrdersAPI, Request
from src.server import serve


def call(api: OrdersAPI, method: str, path: str, body: object = None, **headers: str):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    return api.handle(Request(method, path, {k.lower().replace("_", "-"): v for k, v in headers.items()}, raw))


BOOK = {"item": "book", "qty": 1}


def test_post_creates_with_201_location_and_etag():
    api = OrdersAPI()
    r = call(api, "POST", "/orders", BOOK)
    assert r.status == 201 and r.headers["Location"] == "/orders/1" and r.headers["ETag"] == '"v1"'
    assert json.loads(call(api, "GET", "/orders/1").body) == {"id": "1", **BOOK}


def test_get_is_safe_it_changes_nothing():
    api = OrdersAPI()
    call(api, "PUT", "/orders/a", BOOK)
    before = (dict(api.orders), dict(api.versions))
    for _ in range(5):
        call(api, "GET", "/orders/a")
        call(api, "GET", "/orders")
    assert (api.orders, api.versions) == before


def test_matching_if_none_match_gets_304_with_no_body():
    api = OrdersAPI()
    call(api, "PUT", "/orders/a", BOOK)
    r = call(api, "GET", "/orders/a", if_none_match='"v1"')
    assert r.status == 304 and r.body == b""
    call(api, "PUT", "/orders/a", {"item": "book", "qty": 2})
    assert call(api, "GET", "/orders/a", if_none_match='"v1"').status == 200  # changed: send it again


def test_stale_if_match_is_refused_with_412_and_nothing_changes():
    api = OrdersAPI()
    call(api, "PUT", "/orders/a", BOOK)
    call(api, "PUT", "/orders/a", {"item": "book", "qty": 2}, if_match='"v1"')  # now at v2
    r = call(api, "PUT", "/orders/a", {"item": "book", "qty": 9}, if_match='"v1"')
    assert r.status == 412 and api.orders["a"]["qty"] == 2


def test_wrong_method_is_405_and_allow_lists_the_right_ones():
    r = call(OrdersAPI(), "PATCH", "/orders/1", {"qty": 2})
    assert r.status == 405 and r.headers["Allow"] == "GET, PUT, DELETE"


def test_unreadable_body_is_400_but_readable_invalid_body_is_422():
    api = OrdersAPI()
    assert call(api, "POST", "/orders", b"{oops").status == 400
    assert call(api, "POST", "/orders", {"item": "pen", "qty": 0}).status == 422
    assert call(api, "POST", "/orders", {"item": "pen"}).status == 422
    assert api.orders == {}  # nothing was created


def test_put_and_delete_are_idempotent_post_is_not():
    api = OrdersAPI()
    puts = [call(api, "PUT", "/orders/a", BOOK).status for _ in range(3)]
    assert puts == [201, 200, 200] and len(api.orders) == 1  # same state however often it's sent
    for _ in range(3):
        call(api, "POST", "/orders", BOOK)
    assert len(api.orders) == 4  # three POSTs, three new orders
    assert [call(api, "DELETE", "/orders/a").status for _ in range(2)] == [204, 404]
    assert "a" not in api.orders  # the second DELETE answered 404, but the state is the same


def test_retries_after_lost_responses_duplicate_posts_but_not_puts():
    stored = {}
    for method in ("POST", "PUT"):
        api = OrdersAPI()
        with serve(api) as base, httpx.Client(transport=LossyTransport(0.3, seed=1), base_url=base) as client:
            for i in range(50):
                url = "/orders" if method == "POST" else f"/orders/op-{i}"
                send_with_retries(client, method, url, {"item": f"i{i}", "qty": 1})
        stored[method] = len(api.orders)
    assert stored["POST"] > 50  # each retry after a lost response made a duplicate
    assert stored["PUT"] == 50  # retries rewrote the same orders


def lost_update(clients_send_if_match: bool, server_checks: bool = True) -> int:
    api = OrdersAPI(check_preconditions=server_checks)
    call(api, "PUT", "/orders/42", {"item": "pen", "qty": 1})
    etag = call(api, "GET", "/orders/42").headers["ETag"]  # Alice and Bob both read v1
    cond = {"if_match": etag} if clients_send_if_match else {}
    call(api, "PUT", "/orders/42", {"item": "pen", "qty": 5}, **cond)  # Alice
    bob = call(api, "PUT", "/orders/42", {"item": "pencil", "qty": 1}, **cond)  # Bob, from his stale copy
    if bob.status == 412:
        fresh = call(api, "GET", "/orders/42")
        qty = json.loads(fresh.body)["qty"]
        call(api, "PUT", "/orders/42", {"item": "pencil", "qty": qty}, if_match=fresh.headers["ETag"])
    return api.orders["42"]["qty"]


def test_if_match_prevents_the_lost_update():
    assert lost_update(clients_send_if_match=False) == 1  # Alice's qty 5 silently overwritten
    assert lost_update(clients_send_if_match=True) == 5  # Bob got 412, re-read, kept Alice's change
    assert lost_update(clients_send_if_match=True, server_checks=False) == 1  # only works if the server checks


def test_fastapi_version_gives_the_same_answers_over_http():
    with serve(OrdersAPI()) as ours, run_uvicorn(build_app()) as theirs:
        for base in (ours, theirs):
            with httpx.Client(base_url=base) as c:
                assert c.post("/orders", json=BOOK).status_code == 201
                assert c.get("/orders/1", headers={"If-None-Match": '"v1"'}).status_code == 304
                assert c.put("/orders/1", json=BOOK, headers={"If-Match": '"v9"'}).status_code == 412
                assert c.get("/orders/99").status_code == 404
                assert c.delete("/orders/1").status_code == 204
