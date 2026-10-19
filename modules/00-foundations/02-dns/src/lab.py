"""
A three-level DNS tree on localhost, so resolution can be watched step by step, offline:

    root server        zone "."          198.51.100.1   "test. is served by ns.test."
    TLD server         zone "test."      198.51.100.2   "lab.test. is served by ns1.lab.test."
    authoritative      zone "lab.test."  198.51.100.3   "shop.lab.test. is 10.0.0.1"

The IPs come from a range reserved for documentation (RFC 5737) and appear in referrals,
just like real glue. All three servers actually listen on 127.0.0.1, each on its own port,
and `transport` maps each IP to its port.
"""
from __future__ import annotations

from .dnswire import Record
from .nameserver import NameServer
from .resolver import udp_exchange

DELEGATION_TTL = 172_800  # 2 days: the TTL real root and .com servers put on their referrals


class Clock:
    """Simulated time, so the demo can jump 300 s (or a day) ahead without waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Lab:
    def __init__(self, ttl: int = 300):
        self.root = NameServer(".", [
            Record("test.", "NS", DELEGATION_TTL, "ns.test."),
            Record("ns.test.", "A", DELEGATION_TTL, "198.51.100.2"),
        ])
        self.tld = NameServer("test.", [
            Record("lab.test.", "NS", DELEGATION_TTL, "ns1.lab.test."),
            Record("ns1.lab.test.", "A", DELEGATION_TTL, "198.51.100.3"),
        ])
        self.auth = NameServer("lab.test.", [
            Record("lab.test.", "NS", DELEGATION_TTL, "ns1.lab.test."),
            Record("ns1.lab.test.", "A", DELEGATION_TTL, "198.51.100.3"),
            Record("shop.lab.test.", "A", ttl, "10.0.0.1"),
            Record("api.lab.test.", "A", ttl, "10.0.0.7"),
        ])
        self.servers = (self.root, self.tld, self.auth)
        self.root_hints = {"lab-root": "198.51.100.1"}
        self._ports = {"198.51.100.1": self.root.port, "198.51.100.2": self.tld.port, "198.51.100.3": self.auth.port}

    def __enter__(self) -> Lab:
        for server in self.servers:
            server.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        for server in self.servers:
            server.__exit__()

    def transport(self, packet: bytes, ip: str) -> bytes:
        """Real UDP, but to a local port. A short timeout keeps the outage demo quick."""
        return udp_exchange(packet, ("127.0.0.1", self._ports[ip]), timeout=0.2)
