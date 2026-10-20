"""
REST semantics from scratch: an orders API in which every response follows HTTP's rules.

    resource         URI             methods
    the collection   /orders         GET (list), POST (create; the server picks the id)
    one order        /orders/{id}    GET, PUT (create or replace; the client picks the id), DELETE

The status code tells the client what happened and what to do next. The method's
semantics (safe? idempotent?) tell it whether a retry is harmless. ETags let it skip
downloads it already has (304) and refuse to overwrite changes it never saw (412).
"""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

FIELDS = {"item": str, "qty": int}


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)  # names lower-cased
    body: bytes = b""


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""


def json_response(status: int, data: object, **headers: str) -> Response:
    return Response(status, {"Content-Type": "application/json", **headers}, json.dumps(data).encode())


def problem(status: int, detail: str, **headers: str) -> Response:
    """Errors get a body too: the code says what kind of failure, the body says which field."""
    return json_response(status, {"error": detail}, **headers)


class OrdersAPI:
    def __init__(self, check_preconditions: bool = True):
        self.orders: dict[str, dict] = {}
        self.versions: dict[str, int] = {}  # bumps on every change; the ETag is derived from it
        self.next_id = 1
        self.check_preconditions = check_preconditions  # Break it: False ignores If-Match
        self._lock = threading.Lock()  # requests arrive on many threads

    def handle(self, req: Request) -> Response:
        routes: dict[str, Callable[..., Response]]
        if req.path == "/orders":
            routes, args = {"GET": self.list, "POST": self.create}, ()
        elif match := re.fullmatch(r"/orders/([\w-]+)", req.path):
            routes, args = {"GET": self.read, "PUT": self.replace, "DELETE": self.delete}, (match[1],)
        else:
            return problem(404, f"no resource at {req.path}")
        if req.method not in routes:
            # The URI exists, the verb doesn't apply to it: 405, and say which verbs do.
            return problem(405, f"{req.method} not allowed here", Allow=", ".join(routes))
        with self._lock:
            return routes[req.method](req, *args)

    # GET: safe (changes nothing) and idempotent.
    def list(self, req: Request) -> Response:
        return json_response(200, [{"id": oid, **order} for oid, order in self.orders.items()])

    def read(self, req: Request, oid: str) -> Response:
        if oid not in self.orders:
            return problem(404, f"order {oid} not found")
        etag = self.etag(oid)
        if req.headers.get("if-none-match") == etag:
            return Response(304, {"ETag": etag})  # "your copy is still current": no body sent
        return json_response(200, {"id": oid, **self.orders[oid]}, ETag=etag)

    # POST: neither safe nor idempotent. Each call creates a new order with a new id.
    def create(self, req: Request) -> Response:
        data = parse_order(req.body)
        if isinstance(data, Response):
            return data
        oid = str(self.next_id)
        self.next_id += 1
        self._save(oid, data)
        return json_response(201, {"id": oid, **data}, Location=f"/orders/{oid}", ETag=self.etag(oid))

    # PUT: idempotent. "Make /orders/{id} be exactly this" gives the same state however often it's sent.
    def replace(self, req: Request, oid: str) -> Response:
        data = parse_order(req.body)
        if isinstance(data, Response):
            return data
        if failed := self._precondition_failed(req, oid):
            return failed
        created = oid not in self.orders
        self._save(oid, data)
        headers = {"ETag": self.etag(oid), **({"Location": f"/orders/{oid}"} if created else {})}
        return json_response(201 if created else 200, {"id": oid, **data}, **headers)

    # DELETE: idempotent. The second call finds nothing (404), but the state is the same either way.
    def delete(self, req: Request, oid: str) -> Response:
        if oid not in self.orders:
            return problem(404, f"order {oid} not found")
        if failed := self._precondition_failed(req, oid):
            return failed
        del self.orders[oid]
        return Response(204)  # success, and nothing to say

    def etag(self, oid: str) -> str:
        return f'"v{self.versions[oid]}"'  # quoted, as the spec requires

    def _save(self, oid: str, data: dict) -> None:
        self.orders[oid] = data
        self.versions[oid] = self.versions.get(oid, 0) + 1

    def _precondition_failed(self, req: Request, oid: str) -> Response | None:
        """If-Match: "only change it if it's still the version I read". Without this check,
        two clients that read the same version silently overwrite each other (a lost update)."""
        expected = req.headers.get("if-match")
        if not self.check_preconditions or expected is None:
            return None
        current = self.etag(oid) if oid in self.orders else None
        if current is None or expected not in ("*", current):
            return problem(412, f"order {oid} is at {current}, you sent If-Match {expected}")
        return None


def parse_order(body: bytes) -> dict | Response:
    try:
        data = json.loads(body)
    except ValueError:
        return problem(400, "body is not valid JSON")  # we can't even read it
    if (not isinstance(data, dict) or set(data) != set(FIELDS)
            or any(type(data[k]) is not t for k, t in FIELDS.items()) or data["qty"] < 1):
        return problem(422, 'expected {"item": string, "qty": integer >= 1}')  # readable, but wrong
    return data
