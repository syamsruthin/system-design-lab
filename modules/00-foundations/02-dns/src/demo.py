"""
DNS resolution & TTLs: four experiments that make it visible.

    make run                    # sections 1-3 use a DNS tree on localhost; section 4 needs internet
    OUTAGE=1 make run           # Break it: the authoritative server dies instead of the record changing
    OUTAGE=1 TTL=30 make run    # Break it: the same outage with a 30-second TTL
    NAME=github.com make run    # section 4 for another domain
"""
from __future__ import annotations

import os
import random

import dns.exception
import dns.message
import dns.query
import dns.resolver
import dns.version

from .dnswire import AA, QR, decode, make_query
from .lab import Clock, Lab
from .resolver import ResolutionError, Resolver, Step, ask

TTL = max(int(os.environ.get("TTL", 300)), 10)
OUTAGE = os.environ.get("OUTAGE") == "1"
NAME = os.environ.get("NAME", "example.com")
CHANGE_AT = TTL // 5  # the simulated second when the record changes (or its server dies)
PUBLIC_RESOLVERS = {"1.1.1.1": "Cloudflare", "8.8.8.8": "Google", "9.9.9.9": "Quad9"}


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def human(seconds: float) -> str:
    for unit, size in (("day", 86_400), ("h", 3_600), ("min", 60)):
        if seconds >= size:
            value = f"{seconds / size:.1f}".rstrip("0").rstrip(".")
            return f"{value} {unit}" + ("s" if unit == "day" and value != "1" else "")
    return f"{seconds:.0f} s"


def hexbytes(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def steps_table(steps: list[Step], with_time: bool) -> None:
    headers = ["step", "asked", "IP", *(["took"] if with_time else []), "it replied"]
    rows = [[str(i), s.server, s.ip, *([f"{s.ms:5.1f} ms"] if with_time else []), s.outcome]
            for i, s in enumerate(steps, 1)]
    table(headers, rows)


def experiment_wire() -> None:
    print("\n1) A DNS query is a tiny binary message, sent in a single UDP packet")
    query = make_query("shop.lab.test", query_id=0x1A2B)  # a fixed ID keeps this printout stable
    name_end = query.index(b"\x00", 12) + 1  # the name runs from byte 12 to its zero byte
    labels = " ".join(f'{len(label)} "{label}"' for label in "shop.lab.test".split(".")) + " 0"
    print(f"  query for shop.lab.test. A ({len(query)} bytes):")
    table(["bytes", "meaning"], [
        [hexbytes(query[0:2]), f"ID {0x1A2B}: the reply must carry the same ID"],
        [hexbytes(query[2:4]), "flags: a query; recursion not desired (we walk the tree ourselves)"],
        [hexbytes(query[4:12]), "counts: 1 question, 0 answers, 0 authority, 1 additional"],
        [hexbytes(query[12:name_end]), f"the name, as length-prefixed labels: {labels}"],
        [hexbytes(query[name_end:name_end + 4]), "type 1 = A (IPv4 address), class 1 = IN (internet)"],
        [hexbytes(query[name_end + 4:]), 'EDNS: "I accept UDP replies up to 1232 bytes"'],
    ])
    with Lab(TTL) as lab:
        raw = lab.transport(query, "198.51.100.3")
        reply = decode(raw)
        flags = ", ".join(label for bit, label in ((QR, "response"), (AA, "authoritative")) if reply.flags & bit)
        print(f"  reply from ns1.lab.test. ({len(raw)} bytes, ID {reply.id}, flags: {flags}):")
        for r in reply.answers:
            print(f"    {r.name}  TTL {r.ttl}  {r.type}  {r.data}")
        theirs = dns.query.udp(dns.message.make_query("shop.lab.test", "A"), "127.0.0.1", timeout=2, port=lab.auth.port)
    print(f"  dnspython {dns.version.version} reads our query as : {dns.message.from_wire(query).question[0]}")
    print(f"  dnspython asks our server, gets : {theirs.answer[0]}")
    print(f"  → {len(query)} bytes out, {len(raw)} back, no connection to set up: that's why DNS runs over UDP.")


def experiment_walk() -> None:
    print("\n2) Resolution walks the tree: root → test. → lab.test. (three name servers on localhost)")
    with Lab(TTL) as lab:
        resolver = Resolver(lab.root_hints, lab.transport, clock=Clock(), seed=7)
        cold = resolver.resolve("shop.lab.test")
        print(f"  shop.lab.test. with an empty cache: {len(cold.steps)} queries")
        steps_table(cold.steps, with_time=False)
        sibling = resolver.resolve("api.lab.test")
        print(f"  api.lab.test. next  : {len(sibling.steps)} query, straight to {sibling.steps[0].server} "
              f"(the referrals are cached) → {sibling.addresses[0]}")
        again = resolver.resolve("shop.lab.test")
        print(f"  shop.lab.test. again: {len(again.steps)} queries, from the cache → {again.addresses[0]} "
              f"({again.ttl} s of TTL left)")
    print("  → each server only knows the next step down; caching every step lets later lookups skip the walk.")


def experiment_ttl() -> None:
    print(f"\n3) TTL: how long anyone may reuse an answer (simulated clock, record TTL {TTL} s)")
    clock = Clock()
    rows = []
    with Lab(TTL) as lab:
        resolver = Resolver(lab.root_hints, lab.transport, clock=clock, seed=7)
        for t in (0, 1, CHANGE_AT, CHANGE_AT + 1, TTL - 1, TTL):
            clock.now = t
            if t == CHANGE_AT:
                if OUTAGE:
                    lab.auth.down = True
                    rows.append([f"{t} s", "!! the name server for lab.test. goes down", "", "", ""])
                else:
                    lab.auth.set_address("shop.lab.test.", "10.0.0.2")
                    rows.append([f"{t} s", "!! operator moves shop.lab.test. to 10.0.0.2", "", "", ""])
                continue
            sent = resolver.queries_sent
            try:
                r = resolver.resolve("shop.lab.test")
            except ResolutionError:
                rows.append([f"{t} s", "lookup shop.lab.test.", "FAILED: no name server replied", "",
                             str(resolver.queries_sent - sent)])
                continue
            current = lab.auth.find("shop.lab.test.", "A")[0].data
            note = ("  ← old address!" if r.addresses[0] != current
                    else "  ← server is down; the cache answers" if OUTAGE and t > CHANGE_AT else "")
            source = f"cache, {r.ttl} s left" if r.from_cache else "name servers"
            rows.append([f"{t} s", "lookup shop.lab.test.", r.addresses[0] + note, source,
                         str(resolver.queries_sent - sent)])
    table(["time", "what happens", "resolver answers", "from", "queries"], rows)
    if OUTAGE:
        print(f"  → the cache hid the outage for {TTL - CHANGE_AT} s, then the name stopped resolving.")
    else:
        print(f"  → the change reached this resolver {TTL - CHANGE_AT} s after it was made. "
              "Nothing is pushed: the cached copy just expires.")


def experiment_ttl_sweep(change_at: int = 1_000) -> None:
    print(f"\n   Picking a TTL: one lookup per second; the address changes at t = {change_at:,} s")
    rows = []
    for ttl in (30, 300, 3_600, 86_400):
        clock = Clock()
        with Lab(ttl) as lab:
            resolver = Resolver(lab.root_hints, lab.transport, clock=clock, seed=7)
            stale, noticed, t = 0, None, 0
            while t < 3_600 or noticed is None:  # run at least an hour, and until the change shows
                clock.now = t
                if t == change_at:
                    lab.auth.set_address("shop.lab.test.", "10.0.0.2")
                answer = resolver.resolve("shop.lab.test").addresses[0]
                if t >= change_at and noticed is None:
                    if answer == "10.0.0.1":
                        stale += 1
                    else:
                        noticed = t
                if t == 3_599:
                    queries, hit_ratio = resolver.queries_sent, resolver.hits / (t + 1)
                t += 1
        rows.append([human(ttl), str(queries), f"{hit_ratio:.2%}", f"{stale:,}", human(noticed - change_at)])
    table(["record TTL", "queries to name servers, 1st hour", "cache hit ratio",
           "lookups given the OLD address", "change visible after"], rows)
    print("  → a short TTL shows changes fast but multiplies the queries; with a long one, changes take hours.")


def experiment_internet() -> None:
    print(f"\n4) The real internet: resolve {NAME} starting at a root server, the way 1.1.1.1 would")
    resolver = Resolver(seed=7)
    try:
        cold = resolver.resolve(NAME)
    except (OSError, ResolutionError) as err:
        print(f"  skipped (offline, or UDP port 53 blocked?): {err}")
        return
    steps_table(cold.steps, with_time=True)
    again = resolver.resolve(NAME)
    print(f"  cold: {len(cold.steps)} queries, {sum(s.ms for s in cold.steps):.1f} ms. "
          f"Asked again: {len(again.steps)} queries, answered from the cache.")
    try:
        system = sorted(rr.address for rr in dns.resolver.resolve(NAME, "A"))
        verdict = "the same ✓" if system == sorted(cold.addresses) else "different (CDNs can tailor answers)"
        print(f"  dnspython, through your computer's usual resolver: {', '.join(system)}: {verdict}")
    except dns.exception.DNSException as err:
        print(f"  dnspython through your usual resolver failed: {err}")

    authority = next(s for s in reversed(cold.steps) if s.kind == "answer")
    full = min(r.ttl for r in ask(authority.ip, NAME, query_id=random.getrandbits(16)).answers)
    rows = [[f"{authority.server} (authoritative)", str(full), "the source: always the full TTL"]]
    for ip, who in PUBLIC_RESOLVERS.items():
        try:  # three queries back to back: they may land on different caches behind the same IP
            ttls = [min(r.ttl for r in ask(ip, NAME, query_id=random.getrandbits(16), recursion_desired=True).answers)
                    for _ in range(3)]
            rows.append([f"{ip} ({who})", " · ".join(map(str, ttls)), ", ".join(f"{full - t} s" for t in ttls)])
        except (OSError, ResolutionError, ValueError):
            rows.append([f"{ip} ({who})", "—", "no reply"])
    print("\n  The same record, asked three times at each public resolver:")
    table(["asked", "TTL left", "age of each copy"], rows)
    print("  → one resolver IP is many caches, each counting down its own copy. That's \"DNS propagation\":")
    print("    no push, just copies expiring at different times.")


if __name__ == "__main__":
    print("=" * 78)
    print(" DNS resolution & TTLs: the wire format, the tree walk, caching, the real internet")
    print("=" * 78)
    experiment_wire()
    experiment_walk()
    experiment_ttl()
    experiment_ttl_sweep()
    experiment_internet()
