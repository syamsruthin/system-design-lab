"""
Protocol Buffers on the wire, from scratch: the binary format gRPC sends.

A message is a flat run of fields, each one a key followed by a value:

    key     a varint: (field_number << 3) | wire_type
    value   wire type 0 (VARINT): the number itself, as a varint (ints, bools)
            wire type 2 (LEN):    a varint length, then that many bytes (strings, nested messages)

Field *names* never travel. Both sides compiled the same schema, so they agree that field 1
is "name". That, and varints instead of digits, is why protobuf is much smaller than JSON.

The schema used here, as it would appear in a .proto file:

    message ProfileRequest { int32 user_id = 1; int32 limit = 2; }
    message OrderSummary   { string item = 1; string status = 2; }
    message ProfileScreen  { string name = 1; repeated OrderSummary orders = 2; }
"""
from __future__ import annotations

VARINT, LEN = 0, 2


def encode_varint(n: int) -> bytes:
    """7 bits per byte, lowest bits first; a set top bit means "more bytes follow". 150 → 96 01."""
    if n < 0:
        raise ValueError("this encoder only handles non-negative numbers")
    out = bytearray()
    while True:
        low7, n = n & 0x7F, n >> 7
        out.append(low7 | 0x80 if n else low7)
        if not n:
            return bytes(out)


def decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def encode_field(number: int, value: int | str | bytes) -> bytes:
    if isinstance(value, int):
        return encode_varint(number << 3 | VARINT) + encode_varint(value)
    data = value.encode() if isinstance(value, str) else value
    return encode_varint(number << 3 | LEN) + encode_varint(len(data)) + data


def decode_fields(buf: bytes) -> list[tuple[int, int | bytes]]:
    """Split a message into (field number, raw value) pairs, in wire order."""
    fields, pos = [], 0
    while pos < len(buf):
        key, pos = decode_varint(buf, pos)
        number, wire_type = key >> 3, key & 0x7
        if wire_type == VARINT:
            value, pos = decode_varint(buf, pos)
        elif wire_type == LEN:
            length, pos = decode_varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        else:
            raise ValueError(f"wire type {wire_type} isn't used by this schema")
        fields.append((number, value))
    return fields


# --- The schema above, as encode/decode functions (what protoc would generate for you) ---

def encode_request(req: dict) -> bytes:
    return encode_field(1, req["user_id"]) + encode_field(2, req["limit"])


def decode_request(buf: bytes) -> dict:
    values = dict(decode_fields(buf))
    return {"user_id": values.get(1, 0), "limit": values.get(2, 0)}  # missing field = default 0


def encode_profile(screen: dict) -> bytes:
    out = encode_field(1, screen["name"])
    for order in screen["orders"]:  # "repeated": the same field number, once per element
        nested = encode_field(1, order["item"]) + encode_field(2, order["status"])
        out += encode_field(2, nested)  # a nested message is just length-delimited bytes
    return out


def decode_profile(buf: bytes) -> dict:
    screen: dict = {"name": "", "orders": []}
    for number, value in decode_fields(buf):
        if number == 1:
            screen["name"] = value.decode()
        elif number == 2:
            inner = dict(decode_fields(value))
            screen["orders"].append({"item": inner.get(1, b"").decode(), "status": inner.get(2, b"").decode()})
        # Any other field number is from a newer schema: skip it. Old clients keep working.
    return screen
