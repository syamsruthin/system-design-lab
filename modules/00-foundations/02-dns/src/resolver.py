"""
An iterative resolver with a TTL cache: the job your ISP's resolver, 1.1.1.1 or 8.8.8.8
does for every device behind it.

    1. Answer from the cache if the record's TTL hasn't run out.
    2. Otherwise start at the closest name servers we know (a root server, if nothing better),
       follow each referral one level down, until a server answers with authority.
    3. Cache the answer and every referral for their TTLs, so later lookups skip most of the walk.
"""
from __future__ import annotations

import random
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .dnswire import AA, NXDOMAIN, Message, Record, decode, make_query
from .nameserver import suffixes

# The one thing a resolver must know up front. Everything else it learns by asking.
ROOT_HINTS = {"a.root-servers.net.": "198.41.0.4"}

Transport = Callable[[bytes, str], bytes]  # (query packet, server IP) → response packet


def udp_exchange(packet: bytes, address: tuple[str, int], timeout: float) -> bytes:
    # A fresh socket per query gets a fresh random source port from the OS, which makes
    # forged answers harder to land (the attacker must guess the port and the query ID).
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, address)
        return sock.recvfrom(4096)[0]


def internet(packet: bytes, ip: str) -> bytes:
    return udp_exchange(packet, (ip, 53), timeout=2.0)  # DNS servers listen on UDP port 53


class ResolutionError(Exception):
    pass


def ask(ip: str, name: str, *, query_id: int, recursion_desired: bool = False,
        transport: Transport = internet) -> Message:
    """One query to one server. Raises OSError on timeout, ResolutionError on a forged reply."""
    response = decode(transport(make_query(name, query_id=query_id, recursion_desired=recursion_desired), ip))
    if response.id != query_id:  # not the answer to OUR question: possibly an attacker's
        raise ResolutionError("reply ignored: its ID doesn't match the query")
    return response


@dataclass
class Step:
    server: str
    ip: str
    kind: str     # "answer", "referral", "nxdomain" or "error"
    outcome: str  # human-readable summary for the demo
    ms: float


@dataclass
class Result:
    name: str
    addresses: list[str]
    ttl: int           # seconds until this answer must be fetched again
    from_cache: bool
    steps: list[Step] = field(default_factory=list)  # queries sent for this lookup


class Resolver:
    def __init__(self, root_hints: dict[str, str] = ROOT_HINTS, transport: Transport = internet,
                 clock: Callable[[], float] = time.monotonic, seed: int | None = None):
        self.root_hints = root_hints
        self.transport = transport
        self.clock = clock  # injectable, so the demo can jump ahead in time
        # Real resolvers draw query IDs from a cryptographic RNG; a seed only makes the demo reproducible.
        self._rng = random.Random(seed)
        self.cache: dict[tuple[str, str], tuple[list[str], float]] = {}  # (name, type) → (values, expires at)
        self.queries_sent = 0
        self.hits = 0
        self.misses = 0

    def resolve(self, name: str) -> Result:
        name = name.lower().rstrip(".") + "."
        if cached := self._cached(name, "A"):
            self.hits += 1
            addresses, expires_at = cached
            return Result(name, addresses, int(expires_at - self.clock()), from_cache=True)
        self.misses += 1
        steps: list[Step] = []
        servers = self._closest_servers(name, steps)
        for _ in range(16):  # more referrals than this means a broken delegation loop
            response = self._ask(servers, name, steps)
            if response.rcode == NXDOMAIN:
                raise ResolutionError(f"{name} does not exist (NXDOMAIN)")
            referral = [r for r in response.authority if r.type == "NS"]
            if response.answers or not referral or response.flags & AA:
                addresses = [r.data for r in response.answers if r.type == "A"]
                ttl = min((r.ttl for r in response.answers), default=0)
                self._store(name, "A", addresses, ttl)
                return Result(name, addresses, ttl, from_cache=False, steps=steps)
            servers = self._follow(response, steps)
        raise ResolutionError(f"too many referrals while resolving {name}")

    def _ask(self, servers: list[tuple[str, str]], name: str, steps: list[Step]) -> Message:
        """Try each name server in turn until one replies."""
        for server, ip in servers:
            self.queries_sent += 1
            start = time.perf_counter()
            try:
                response = ask(ip, name, query_id=self._rng.getrandbits(16), transport=self.transport)
            except (OSError, ResolutionError) as err:
                reason = str(err) if isinstance(err, ResolutionError) else "no reply (timed out)"
                steps.append(Step(server, ip, "error", reason, (time.perf_counter() - start) * 1000))
                continue
            steps.append(Step(server, ip, *describe(response), (time.perf_counter() - start) * 1000))
            return response
        raise ResolutionError(f"no name server replied for {name}")

    def _follow(self, response: Message, steps: list[Step]) -> list[tuple[str, str]]:
        """A referral says "zone X is served by these name servers". Cache that, and the glue
        addresses that came with it, each for its own TTL; then return who to ask next."""
        delegation = [r for r in response.authority if r.type == "NS"]
        zone = delegation[0].name
        self._store(zone, "NS", [r.data for r in delegation], min(r.ttl for r in delegation))
        glue: dict[str, list[Record]] = {}
        for r in response.additional:
            if r.type == "A":  # we speak IPv4 only, so AAAA glue is skipped
                glue.setdefault(r.name, []).append(r)
        for host, records in glue.items():
            self._store(host, "A", [r.data for r in records], min(r.ttl for r in records))
        return self._servers_for(zone, steps)

    def _servers_for(self, zone: str, steps: list[Step]) -> list[tuple[str, str]]:
        """(name, IP) of each cached name server for a zone. If the referral brought no glue,
        look up a name server's address first: a lookup inside the lookup."""
        ns_names = (self._cached(zone, "NS") or ([], 0.0))[0]
        servers = []
        for ns in ns_names:
            for ip in (self._cached(ns, "A") or ([], 0.0))[0]:
                servers.append((ns, ip))
        if not servers and ns_names:
            found = self.resolve(ns_names[0])
            steps.extend(found.steps)
            servers = [(ns_names[0], ip) for ip in found.addresses]
        return servers

    def _closest_servers(self, name: str, steps: list[Step]) -> list[tuple[str, str]]:
        """Start as far down the tree as the cache allows: name servers cached for
        lab.test. beat those for test., which beat the root."""
        for zone in suffixes(name):
            if self._cached(zone, "NS") and (servers := self._servers_for(zone, steps)):
                return servers
        return list(self.root_hints.items())

    def _cached(self, name: str, rtype: str) -> tuple[list[str], float] | None:
        entry = self.cache.get((name, rtype))
        if entry and entry[1] > self.clock():
            return entry
        return None  # never cached, or its TTL ran out: an expired entry counts for nothing

    def _store(self, name: str, rtype: str, values: list[str], ttl: int) -> None:
        self.cache[(name, rtype)] = (values, self.clock() + ttl)


def describe(response: Message) -> tuple[str, str]:
    """(kind, summary) of a response, for the step-by-step trace."""
    if response.rcode == NXDOMAIN:
        return "nxdomain", "NXDOMAIN: no such name"
    if response.answers:
        ips = ", ".join(r.data for r in response.answers if r.type == "A")
        return "answer", f"ANSWER {ips} (TTL {min(r.ttl for r in response.answers)})"
    delegation = [r for r in response.authority if r.type == "NS"]
    if delegation:
        more = f" + {len(delegation) - 1} more" if len(delegation) > 1 else ""
        return "referral", f"referral: {delegation[0].name} is served by {delegation[0].data}{more}"
    return "answer", "no records of that type"
