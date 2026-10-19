"""
A DNS name server for one zone, on a real UDP socket.

It knows only its own zone. For a name it owns, it gives an authoritative answer. For a
name inside a zone it has delegated, it gives a referral ("ask them"): the NS records of
the servers responsible, plus their addresses as glue. That is all a root server or a
.com server ever does.
"""
from __future__ import annotations

import socket
import threading

from .dnswire import AA, NXDOMAIN, QR, RD, Message, Record, decode, encode

REFUSED = 5  # response code: "that name isn't in my zone, don't ask me"


def suffixes(name: str) -> list[str]:
    """'shop.lab.test.' → ['shop.lab.test.', 'lab.test.', 'test.', '.']: every zone it could be in."""
    labels = [label for label in name.split(".") if label]
    return [".".join(labels[i:]) + "." for i in range(len(labels))] + ["."]


class NameServer:
    def __init__(self, zone: str, records: list[Record]):
        self.zone = zone          # e.g. "lab.test.": the part of the tree this server owns
        self.records = records    # its zone file; the demo edits it while the server runs
        self.queries = 0          # queries answered
        self.down = False         # Break it: an outage, the server silently stops answering
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))  # port 0: the OS picks a free one
        self.port: int = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> NameServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()

    def _serve(self) -> None:
        self._sock.settimeout(0.05)  # wake up regularly to notice _stop
        while not self._stop.is_set():
            try:
                packet, client = self._sock.recvfrom(4096)
            except TimeoutError:
                continue
            if self.down:
                continue  # drop it: the asker hears nothing and times out
            self.queries += 1
            self._sock.sendto(encode(self.respond(decode(packet))), client)

    def respond(self, query: Message) -> Message:
        name, rtype = query.question[0].lower(), query.question[1]
        flags = QR | (query.flags & RD)
        # Walk from the full name up towards our own zone. Hitting an NS record set on the
        # way means that part of the tree was handed to someone else: send a referral.
        for cut in suffixes(name):
            if cut == self.zone:
                break
            if delegation := self.find(cut, "NS"):
                hosts = {ns.data for ns in delegation}
                glue = [r for r in self.records if r.type == "A" and r.name in hosts]
                return Message(query.id, flags, query.question, authority=delegation, additional=glue)
        else:
            return Message(query.id, flags | REFUSED, query.question)
        # The name is ours: answer with authority, even if the answer is "no such name".
        exists = any(r.name == name for r in self.records)
        return Message(query.id, flags | AA | (0 if exists else NXDOMAIN), query.question,
                       answers=self.find(name, rtype))

    def find(self, name: str, rtype: str) -> list[Record]:
        return [r for r in self.records if r.name == name and r.type == rtype]

    def set_address(self, name: str, ip: str) -> None:
        """Point a name at a new IP, like an operator moving a site to a new server."""
        self.records = [Record(r.name, r.type, r.ttl, ip) if (r.name, r.type) == (name, "A") else r
                        for r in self.records]
