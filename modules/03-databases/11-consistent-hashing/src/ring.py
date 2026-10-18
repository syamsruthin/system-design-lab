"""
Consistent hashing with virtual nodes, from scratch.

Idea: put servers AND keys on the same circle of hash values (the "ring").
A key belongs to the first server you meet walking clockwise from the key's
position. Adding or removing a server only changes ownership of the arc next to
it, so only ~1/N of keys move instead of almost all of them.
"""
from __future__ import annotations

import bisect
import hashlib
from collections import Counter
from collections.abc import Iterable

RING_SIZE = 2**64


def stable_hash(value: str) -> int:
    """Map a string to a point on a ring of 2^64 positions.

    The hash must be identical on every machine and every process. Python's
    built-in hash() is salted per process (PYTHONHASHSEED), so two app servers
    using it would disagree about which shard owns a key. MD5 is fine here:
    we need uniform spread, not cryptographic security.
    """
    return int.from_bytes(hashlib.md5(value.encode()).digest()[:8], "big")


class ModuloRouter:
    """The naive baseline: node = hash(key) % N.

    Perfectly balanced, but N is baked into every placement: changing N
    remaps almost every key (about N/(N+1) of them when adding one node).
    """

    def __init__(self, nodes: Iterable[str]):
        self.nodes = list(nodes)

    def get_node(self, key: str) -> str:
        return self.nodes[stable_hash(key) % len(self.nodes)]


class ConsistentHashRing:
    """A hash ring where each physical node owns many virtual nodes (vnodes).

    Why vnodes: with one point per server, arcs between points are random and
    very uneven, so one server can own 40% of the ring. Spreading each server
    over many small arcs averages that out. It also means a dead server's keys
    are shared by all survivors instead of dumped on a single neighbour.
    """

    def __init__(self, nodes: Iterable[str] = (), vnodes: int = 150):
        if vnodes < 1:
            raise ValueError("vnodes must be >= 1")
        self.vnodes = vnodes
        self._positions: list[int] = []  # sorted ring positions of every vnode
        self._owners: dict[int, tuple[str, int]] = {}  # position -> (physical node, vnode index)
        self._weights: dict[str, int] = {}
        for node in nodes:
            self.add_node(node)

    @property
    def nodes(self) -> list[str]:
        return list(self._weights)

    def add_node(self, node: str, weight: int = 1) -> None:
        """Place `vnodes * weight` points for this node. A bigger machine gets
        a higher weight, so it owns proportionally more of the ring."""
        if node in self._weights:
            raise ValueError(f"{node} is already on the ring")
        self._weights[node] = weight
        for i in range(self.vnodes * weight):
            pos = stable_hash(f"{node}#{i}")
            if pos in self._owners:  # 64-bit collision: astronomically rare, skip it
                continue
            self._owners[pos] = (node, i)
            bisect.insort(self._positions, pos)

    def remove_node(self, node: str) -> None:
        if node not in self._weights:
            raise KeyError(node)
        del self._weights[node]
        self._positions = [p for p in self._positions if self._owners[p][0] != node]
        self._owners = {p: o for p, o in self._owners.items() if o[0] != node}

    def _index_for(self, key: str) -> int:
        if not self._positions:
            raise LookupError("ring is empty")
        # First vnode at or after the key's position; past the end, wrap to index 0.
        return bisect.bisect_left(self._positions, stable_hash(key)) % len(self._positions)

    def get_node(self, key: str) -> str:
        return self._owners[self._positions[self._index_for(key)]][0]

    def get_nodes(self, key: str, n: int) -> list[str]:
        """Replica placement: keep walking clockwise, collecting DISTINCT physical
        nodes, skipping extra vnodes of a server we already picked. This is how
        Dynamo and Cassandra choose the N replicas for a key."""
        want = min(n, len(self._weights))
        start, out = self._index_for(key), []
        for step in range(len(self._positions)):
            node = self._owners[self._positions[(start + step) % len(self._positions)]][0]
            if node not in out:
                out.append(node)
                if len(out) == want:
                    break
        return out

    def trace(self, key: str) -> dict:
        """Explain one lookup: where the key lands and which vnode catches it."""
        h = stable_hash(key)
        pos = self._positions[self._index_for(key)]
        node, vnode = self._owners[pos]
        return {"key": key, "key_deg": 360 * h / RING_SIZE, "vnode": f"{node}#{vnode}",
                "vnode_deg": 360 * pos / RING_SIZE, "node": node}

    def distribution(self, keys: Iterable[str]) -> Counter[str]:
        return Counter(self.get_node(k) for k in keys)
