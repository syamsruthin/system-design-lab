"""
Consistent hashing demo: four experiments that make the concept visible.

    make run                # default 150 virtual nodes per server
    VNODES=1 make run       # Break it: watch the balance collapse
"""
from __future__ import annotations

import os

from .ring import ConsistentHashRing, ModuloRouter

N_KEYS = 100_000
KEYS = [f"user:{i}" for i in range(N_KEYS)]  # deterministic, so output is reproducible
VNODES = int(os.environ.get("VNODES", 150))
FOUR = ["node-A", "node-B", "node-C", "node-D"]
FIVE = FOUR + ["node-E"]


def pct(n: int, total: int = N_KEYS) -> str:
    return f"{100 * n / total:5.1f}%"


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def moved(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [k for k in KEYS if before[k] != after[k]]


def experiment_add_node() -> None:
    print(f"\n1) Scale out: add a 5th server ({N_KEYS:,} keys, {VNODES} vnodes/server)")
    mod4, mod5 = ModuloRouter(FOUR), ModuloRouter(FIVE)
    ring = ConsistentHashRing(FOUR, vnodes=VNODES)
    before_mod = {k: mod4.get_node(k) for k in KEYS}
    after_mod = {k: mod5.get_node(k) for k in KEYS}
    before_ring = {k: ring.get_node(k) for k in KEYS}
    ring.add_node("node-E")
    after_ring = {k: ring.get_node(k) for k in KEYS}

    m_mod, m_ring = moved(before_mod, after_mod), moved(before_ring, after_ring)
    to_new = sum(after_ring[k] == "node-E" for k in m_ring)
    table(["strategy", "keys moved", "share", "moved keys that went to node-E"], [
        ["hash % N", f"{len(m_mod):,}", pct(len(m_mod)), pct(sum(after_mod[k] == "node-E" for k in m_mod), len(m_mod))],
        ["consistent hash", f"{len(m_ring):,}", pct(len(m_ring)), pct(to_new, len(m_ring))],
        ["ideal (1/5)", f"{N_KEYS // 5:,}", pct(N_KEYS // 5), "100.0%"],
    ])
    print("  → modulo reshuffles ~80% of the cache/shards; the ring moves only what node-E must take.")


def experiment_remove_node() -> None:
    print("\n2) Failure: node-C dies (5 → 4 servers)")
    ring = ConsistentHashRing(FIVE, vnodes=VNODES)
    before = {k: ring.get_node(k) for k in KEYS}
    owned_by_c = sum(v == "node-C" for v in before.values())
    ring.remove_node("node-C")
    after = {k: ring.get_node(k) for k in KEYS}
    m = moved(before, after)
    only_c = all(before[k] == "node-C" for k in m)
    mod5, mod4 = ModuloRouter(FIVE), ModuloRouter(["node-A", "node-B", "node-D", "node-E"])
    m_mod = [k for k in KEYS if mod5.get_node(k) != mod4.get_node(k)]
    print(f"  node-C owned {owned_by_c:,} keys ({pct(owned_by_c).strip()}). Ring moved {len(m):,}; "
          f"all of them were node-C's: {only_c}. Modulo would move {pct(len(m_mod)).strip()}.")
    spread = {n: sum(after[k] == n for k in m) for n in ring.nodes}
    table(["node-C's keys went to", "keys", "share"],
          [[n, f"{c:,}", pct(c, len(m))] for n, c in spread.items()])
    print("  → with vnodes the orphaned keys spread over ALL survivors, so no single neighbour gets swamped.")


def experiment_vnodes() -> None:
    print("\n3) Why virtual nodes? Balance across 5 servers")
    rows = []
    for v in (1, 3, 10, 50, 150, 500):
        dist = ConsistentHashRing(FIVE, vnodes=v).distribution(KEYS)
        shares = [dist.get(n, 0) for n in FIVE]
        rows.append([str(v), pct(max(shares)), pct(min(shares)), f"{max(shares) / (N_KEYS / 5):.2f}×"])
    table(["vnodes/server", "busiest", "quietest", "busiest vs fair share"], rows)
    print("  → one point per server leaves random, lopsided arcs; ~100+ vnodes gets within a few % of fair.")


def experiment_trace_and_replicas() -> None:
    print("\n4) One lookup, step by step, plus replica placement (N=3)")
    ring = ConsistentHashRing(FIVE, vnodes=VNODES)
    for key in ("user:42", "user:1337"):
        t = ring.trace(key)
        print(f"  {key:<10} hashes to {t['key_deg']:6.2f}° → next vnode clockwise is {t['vnode']:<12} "
              f"at {t['vnode_deg']:6.2f}° → stored on {t['node']}; replicas {ring.get_nodes(key, 3)}")

    print("\n   Heterogeneous hardware: node-E is twice as big (weight=2)")
    weighted = ConsistentHashRing(FOUR, vnodes=VNODES)
    weighted.add_node("node-E", weight=2)
    dist = weighted.distribution(KEYS)
    print("   " + "  ".join(f"{n}: {pct(dist[n]).strip()}" for n in FIVE) + "   (fair: 16.7% each, E 33.3%)")


if __name__ == "__main__":
    print("=" * 78)
    print(" Consistent hashing — modulo vs ring, failures, virtual nodes, replicas")
    print("=" * 78)
    experiment_add_node()
    experiment_remove_node()
    experiment_vnodes()
    experiment_trace_and_replicas()
