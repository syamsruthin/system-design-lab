"""Tests that pin down how DNS resolution and TTL caching behave."""
import dns.flags
import dns.message
import dns.query
import dns.rrset
import pytest

from src.dnswire import AA, QR, Message, Record, decode, encode, make_query
from src.lab import Clock, Lab
from src.resolver import ResolutionError, Resolver


def resolver_for(lab: Lab, clock: Clock | None = None) -> Resolver:
    return Resolver(lab.root_hints, lab.transport, clock=clock or Clock(), seed=1)


def test_query_is_a_small_binary_message_that_real_libraries_can_read():
    query = make_query("shop.lab.test", query_id=0x1A2B)
    assert query[:2] == b"\x1a\x2b"  # the ID comes first
    assert query[12:27] == b"\x04shop\x03lab\x04test\x00"  # length-prefixed labels, then a zero
    parsed = dns.message.from_wire(query)
    assert parsed.id == 0x1A2B and str(parsed.question[0]) == "shop.lab.test. IN A"


def test_compressed_names_from_real_servers_are_decoded():
    reply = dns.message.make_response(dns.message.make_query("example.com", "NS"))
    reply.answer.append(dns.rrset.from_text("example.com.", 300, "IN", "NS", "a.ns.example.com.", "b.ns.example.com."))
    wire = reply.to_wire()  # dnspython, like real servers, replaces repeated suffixes with pointers
    assert len(wire) < 80 and b"\xc0" in wire
    assert sorted(r.data for r in decode(wire).answers) == ["a.ns.example.com.", "b.ns.example.com."]


def test_our_name_server_answers_a_real_dns_library():
    with Lab() as lab:
        reply = dns.query.udp(dns.message.make_query("shop.lab.test", "A"), "127.0.0.1", timeout=2, port=lab.auth.port)
    assert reply.answer[0].ttl == 300 and reply.answer[0][0].address == "10.0.0.1"
    assert reply.flags & dns.flags.AA  # it owns the zone, so the answer is authoritative


def test_resolution_follows_referrals_from_root_to_tld_to_authoritative():
    with Lab() as lab:
        result = resolver_for(lab).resolve("shop.lab.test")
    assert result.addresses == ["10.0.0.1"] and not result.from_cache
    assert [s.server for s in result.steps] == ["lab-root", "ns.test.", "ns1.lab.test."]
    assert [s.kind for s in result.steps] == ["referral", "referral", "answer"]


def test_cached_referrals_let_a_sibling_name_skip_the_root_and_tld():
    with Lab() as lab:
        resolver = resolver_for(lab)
        resolver.resolve("shop.lab.test")
        sibling = resolver.resolve("api.lab.test")
    assert sibling.addresses == ["10.0.0.7"]
    assert [s.server for s in sibling.steps] == ["ns1.lab.test."]
    assert lab.root.queries == 1 and lab.tld.queries == 1


def test_cached_answer_costs_no_queries_until_its_ttl_runs_out():
    clock = Clock()
    with Lab(ttl=300) as lab:
        resolver = resolver_for(lab, clock)
        resolver.resolve("shop.lab.test")
        sent = resolver.queries_sent
        clock.now = 299
        hit = resolver.resolve("shop.lab.test")
        assert hit.from_cache and hit.ttl == 1 and resolver.queries_sent == sent
        clock.now = 300
        assert not resolver.resolve("shop.lab.test").from_cache
        assert resolver.queries_sent == sent + 1  # just the authoritative server: referrals are still cached


def test_changed_record_stays_invisible_until_the_ttl_expires():
    clock = Clock()
    with Lab(ttl=300) as lab:
        resolver = resolver_for(lab, clock)
        resolver.resolve("shop.lab.test")
        clock.now = 60
        lab.auth.set_address("shop.lab.test.", "10.0.0.2")
        clock.now = 299
        assert resolver.resolve("shop.lab.test").addresses == ["10.0.0.1"]  # stale, by design
        clock.now = 300
        assert resolver.resolve("shop.lab.test").addresses == ["10.0.0.2"]


def stale_lookups_and_queries(ttl: int, change_at: int = 100, duration: int = 600) -> tuple[int, int]:
    clock = Clock()
    with Lab(ttl=ttl) as lab:
        resolver = resolver_for(lab, clock)
        stale = 0
        for t in range(duration):  # one lookup per simulated second
            clock.now = t
            if t == change_at:
                lab.auth.set_address("shop.lab.test.", "10.0.0.2")
            if resolver.resolve("shop.lab.test").addresses == ["10.0.0.1"] and t >= change_at:
                stale += 1
        return stale, resolver.queries_sent


def test_ttl_bounds_staleness_and_shorter_ttls_cost_more_queries():
    short, long = stale_lookups_and_queries(ttl=30), stale_lookups_and_queries(ttl=300)
    assert short[0] <= 30 and long[0] <= 300  # nobody serves a copy older than its TTL
    assert short[0] < long[0]  # a short TTL spreads a change faster...
    assert short[1] > long[1]  # ...at the price of more queries to the name servers


def test_cache_hides_an_authoritative_outage_until_the_ttl_expires():
    clock = Clock()
    with Lab(ttl=300) as lab:
        resolver = resolver_for(lab, clock)
        resolver.resolve("shop.lab.test")
        lab.auth.down = True
        clock.now = 299
        assert resolver.resolve("shop.lab.test").addresses == ["10.0.0.1"]
        clock.now = 300
        with pytest.raises(ResolutionError):
            resolver.resolve("shop.lab.test")


def test_nonexistent_name_is_nxdomain():
    with Lab() as lab, pytest.raises(ResolutionError, match="NXDOMAIN"):
        resolver_for(lab).resolve("nope.lab.test")


def test_reply_with_the_wrong_id_is_rejected_and_never_cached():
    def forger(packet: bytes, ip: str) -> bytes:  # an attacker racing the real server with a fake answer
        query = decode(packet)
        fake = Record("shop.lab.test.", "A", 86_400, "6.6.6.6")
        return encode(Message(query.id ^ 0xFFFF, QR | AA, query.question, answers=[fake]))

    resolver = Resolver({"evil-root": "203.0.113.66"}, forger, clock=Clock(), seed=1)
    with pytest.raises(ResolutionError):
        resolver.resolve("shop.lab.test")
    assert resolver.cache == {}  # nothing poisoned
