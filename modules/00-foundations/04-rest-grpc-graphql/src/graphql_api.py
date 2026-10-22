"""
The GraphQL side: one endpoint, a typed schema, and a resolver per field.

The client sends a query naming exactly the fields it wants; the server walks that query and
calls the resolver for each field. Resolvers are where GraphQL's two classic costs hide:

    N+1 queries   a per-item resolver (each order's shipment) runs once per item. DataLoader
                  collects those calls within one tick and runs a single batched query instead.
    fan-out       nested lists (friends of friends of ...) multiply the work at every level.
"""
from __future__ import annotations

import strawberry
from strawberry.dataloader import DataLoader
from strawberry.types import Info

from .data import DB


@strawberry.type
class Shipment:
    status: str
    carrier: str
    tracking: str
    eta: str


@strawberry.type
class Order:
    id: int
    item: str
    qty: int
    price_cents: int

    @strawberry.field
    async def shipment(self, info: Info) -> Shipment:
        ctx = info.context
        row = await ctx["shipments"].load(self.id) if ctx["batched"] else ctx["db"].shipment(self.id)
        return Shipment(**{k: row[k] for k in ("status", "carrier", "tracking", "eta")})


@strawberry.type
class User:
    id: int
    name: str
    email: str
    phone: str
    address: str

    @strawberry.field
    async def orders(self, info: Info, limit: int = 3) -> list[Order]:
        ctx = info.context
        rows = await ctx["orders"].load((self.id, limit)) if ctx["batched"] else ctx["db"].orders_of(self.id, limit)
        return [to_order(r) for r in rows]

    @strawberry.field
    async def friends(self, info: Info) -> list[User]:
        ids = await info.context["friend_ids"].load(self.id)
        return [to_user(r) for r in await info.context["users"].load_many(ids)]


@strawberry.type
class Query:
    @strawberry.field
    def user(self, info: Info, id: int) -> User:
        return to_user(info.context["db"].user(id))

    @strawberry.field
    def users(self, info: Info, ids: list[int]) -> list[User]:
        return [to_user(r) for r in info.context["db"].users_by_ids(ids)]


def to_user(row: dict) -> User:
    return User(**{k: row[k] for k in ("id", "name", "email", "phone", "address")})


def to_order(row: dict) -> Order:
    return Order(**{k: row[k] for k in ("id", "item", "qty", "price_cents")})


schema = strawberry.Schema(query=Query)


def make_context(db: DB, batched: bool = True) -> dict:
    """Fresh loaders per request: a DataLoader also caches, and that cache must not leak between users."""

    async def shipments(oids: list[int]) -> list[dict]:
        return db.shipments_for(oids)

    async def orders(keys: list[tuple[int, int]]) -> list[list[dict]]:
        limit = keys[0][1]  # every key in one batch comes from the same query, so the same limit
        return db.orders_of_many([uid for uid, _ in keys], limit)

    async def friend_ids(uids: list[int]) -> list[list[int]]:
        return db.friends_of_many(uids)

    async def users(uids: list[int]) -> list[dict]:
        return db.users_by_ids(uids)

    return {"db": db, "batched": batched, "shipments": DataLoader(shipments), "orders": DataLoader(orders),
            "friend_ids": DataLoader(friend_ids), "users": DataLoader(users)}
