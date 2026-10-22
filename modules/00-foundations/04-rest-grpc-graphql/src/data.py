"""
A small in-memory "database" that counts its queries, so each API style's database cost
is visible. Seeded, so every run builds the same users, orders and friendships.

Each user row is deliberately wide (email, phone, address, bio, ...): real records carry many
fields that any one screen doesn't need, and REST endpoints return all of them.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

ITEMS = ["lamp", "book", "kettle", "chair", "mug", "desk", "pen", "rug"]
STATUSES = ["delivered", "in transit", "packed"]


@dataclass
class DB:
    users: dict[int, dict] = field(default_factory=dict)
    orders: dict[int, list[dict]] = field(default_factory=dict)  # user id → that user's orders, newest first
    shipments: dict[int, dict] = field(default_factory=dict)     # order id → its shipment
    friends: dict[int, list[int]] = field(default_factory=dict)  # user id → friend ids
    queries: int = 0                                             # every method below is one query

    def user(self, uid: int) -> dict:
        self.queries += 1
        return self.users[uid]

    def users_by_ids(self, uids: list[int]) -> list[dict]:
        self.queries += 1  # one "WHERE id IN (...)" query, however many ids
        return [self.users[u] for u in uids]

    def orders_of(self, uid: int, limit: int) -> list[dict]:
        self.queries += 1
        return self.orders[uid][:limit]

    def orders_of_many(self, uids: list[int], limit: int) -> list[list[dict]]:
        self.queries += 1
        return [self.orders[u][:limit] for u in uids]

    def shipment(self, oid: int) -> dict:
        self.queries += 1
        return self.shipments[oid]

    def shipments_for(self, oids: list[int]) -> list[dict]:
        self.queries += 1
        return [self.shipments[o] for o in oids]

    def friends_of_many(self, uids: list[int]) -> list[list[int]]:
        self.queries += 1
        return [self.friends[u] for u in uids]


def make_db(n_users: int = 50, orders_per_user: int = 4, friends_per_user: int = 5, seed: int = 7) -> DB:
    rng = random.Random(seed)
    db, next_order = DB(), 1
    for uid in range(1, n_users + 1):
        db.users[uid] = {
            "id": uid, "name": f"user-{uid}", "email": f"user{uid}@example.com", "phone": f"+1-555-01{uid:02d}",
            "address": f"{uid} Oak Street, Springfield", "bio": "Likes lamps, books and long walks.",
            "avatar_url": f"https://cdn.example.com/avatars/{uid}.png", "created_at": "2025-01-15T10:00:00Z",
        }
        db.orders[uid] = []
        for _ in range(orders_per_user):
            db.orders[uid].append({
                "id": next_order, "user_id": uid, "item": rng.choice(ITEMS), "qty": rng.randint(1, 3),
                "price_cents": rng.randint(500, 9000), "created_at": "2026-10-01T09:30:00Z", "notes": "",
            })
            db.shipments[next_order] = {
                "order_id": next_order, "status": rng.choice(STATUSES), "carrier": "ParcelCo",
                "tracking": f"PC{next_order:08d}", "eta": "2026-10-25",
            }
            next_order += 1
        db.friends[uid] = rng.sample([u for u in range(1, n_users + 1) if u != uid], friends_per_user)
    return db
