"""
DNS on the wire: one small binary message per UDP packet, in each direction.

    header      12 bytes: query ID, flags, and how many records each section below holds
    question    the name and type being asked about ("shop.lab.test.", A)
    answer      records that answer the question
    authority   "not me, ask them": NS records naming the servers of a zone further down
    additional  helpful extras, usually "glue": the IP addresses of those servers

Every record carries a TTL: how many seconds anyone may cache it.
"""
from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass, field

TYPES = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "AAAA": 28, "OPT": 41}
IN = 1  # class "internet": the only class anyone uses

# Bits of the header's 16-bit flags field.
QR = 0x8000  # this message is a response
AA = 0x0400  # authoritative answer: it comes from a server that owns the zone, not from a cache
RD = 0x0100  # recursion desired: "do the whole walk for me" (what your laptop asks a resolver)
NXDOMAIN = 3  # response code (the flags' low 4 bits): the name does not exist


@dataclass
class Record:
    name: str  # absolute names end with a dot, which stands for the root: "shop.lab.test."
    type: str  # "A", "NS", ...
    ttl: int   # seconds anyone may cache this record
    data: str  # "10.0.0.1" for A, a name for NS/CNAME, raw hex for types we don't decode


@dataclass
class Message:
    id: int
    flags: int
    question: tuple[str, str]  # (name, type)
    answers: list[Record] = field(default_factory=list)
    authority: list[Record] = field(default_factory=list)
    additional: list[Record] = field(default_factory=list)

    @property
    def rcode(self) -> int:
        return self.flags & 0x000F


def type_code(name: str) -> int:
    return TYPES[name] if name in TYPES else int(name.removeprefix("TYPE"))


def type_name(code: int) -> str:
    return next((name for name, c in TYPES.items() if c == code), f"TYPE{code}")


def encode_name(name: str) -> bytes:
    r"""'shop.lab.test.' → b'\x04shop\x03lab\x04test\x00': each label after its length, then a 0."""
    labels = [label for label in name.split(".") if label]
    return b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels) + b"\x00"


def make_query(name: str, rtype: str = "A", *, query_id: int, recursion_desired: bool = False) -> bytes:
    header = struct.pack("!6H", query_id, RD if recursion_desired else 0, 1, 0, 0, 1)
    question = encode_name(name) + struct.pack("!2H", type_code(rtype), IN)
    # EDNS(0): an OPT pseudo-record whose class field means "I accept UDP answers up to
    # 1232 bytes". Without it, a server must squeeze its answer into 512 bytes or truncate it.
    edns = encode_name(".") + struct.pack("!2HIH", TYPES["OPT"], 1232, 0, 0)
    return header + question + edns


def encode(msg: Message) -> bytes:
    """Serialise a response. Names are written out in full; compression is optional when sending."""
    counts = (1, len(msg.answers), len(msg.authority), len(msg.additional))
    name, rtype = msg.question
    out = struct.pack("!6H", msg.id, msg.flags, *counts) + encode_name(name) + struct.pack("!2H", type_code(rtype), IN)
    for r in msg.answers + msg.authority + msg.additional:
        rdata = ipaddress.IPv4Address(r.data).packed if r.type == "A" else encode_name(r.data)
        out += encode_name(r.name) + struct.pack("!2HIH", type_code(r.type), IN, r.ttl, len(rdata)) + rdata
    return out


def decode(packet: bytes) -> Message:
    query_id, flags, _qdcount, *counts = struct.unpack_from("!6H", packet)
    name, offset = decode_name(packet, 12)
    qtype, _qclass = struct.unpack_from("!2H", packet, offset)
    offset += 4
    sections: list[list[Record]] = []
    for count in counts:  # answer, authority, additional
        records = []
        for _ in range(count):
            record, offset = decode_record(packet, offset)
            records.append(record)
        sections.append(records)
    return Message(query_id, flags, (name, type_name(qtype)), *sections)


def decode_name(packet: bytes, offset: int) -> tuple[str, int]:
    """Read a name; return it and the offset just after it.

    A length byte with its top two bits set (0xC0) is a compression pointer: the rest of
    the name is at an earlier offset in the packet. Servers use pointers so that a suffix
    like "gtld-servers.net." is written once per packet instead of thirteen times.
    """
    labels: list[str] = []
    resume_at: int | None = None  # where the caller continues, if we followed a pointer
    for _ in range(255):  # names max out at 255 bytes; a malicious packet could make pointers loop forever
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            if resume_at is None:
                resume_at = offset + 2
            offset = struct.unpack_from("!H", packet, offset)[0] & 0x3FFF
            continue
        if length == 0:
            return ".".join(labels) + ".", resume_at if resume_at is not None else offset + 1
        labels.append(packet[offset + 1:offset + 1 + length].decode("ascii"))
        offset += 1 + length
    raise ValueError("name too long, or a compression loop")


def decode_record(packet: bytes, offset: int) -> tuple[Record, int]:
    name, offset = decode_name(packet, offset)
    code, _rclass, ttl, length = struct.unpack_from("!2HIH", packet, offset)
    offset += 10
    rdata = packet[offset:offset + length]
    kind = type_name(code)
    if kind == "A":
        data = str(ipaddress.IPv4Address(rdata))
    elif kind == "AAAA":
        data = str(ipaddress.IPv6Address(rdata))
    elif kind in ("NS", "CNAME"):
        data = decode_name(packet, offset)[0]  # read from the packet: the name may use pointers
    else:
        data = rdata.hex()
    return Record(name, kind, ttl, data), offset + length
