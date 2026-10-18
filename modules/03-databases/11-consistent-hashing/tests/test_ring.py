"""Tests that pin down what makes consistent hashing *consistent*."""
from statistics import pstdev

import pytest

from src.ring import ConsistentHashRing, ModuloRouter

KEYS = [f"key-{i}" for i in range(20_000)]
FOUR = ["A", "B", "C", "D"]


def placement(router) -> dict[str, str]:
    return {k: router.get_node(k) for k in KEYS}


def test_lookup_is_deterministic():
    r1, r2 = ConsistentHashRing(FOUR), ConsistentHashRing(FOUR)
    assert placement(r1) == placement(r2)  # two "app servers" agree without coordinating


def test_adding_a_node_moves_about_one_over_n_keys_and_only_to_the_new_node():
    ring = ConsistentHashRing(FOUR, vnodes=150)
    before = placement(ring)
    ring.add_node("E")
    after = placement(ring)
    moved = [k for k in KEYS if before[k] != after[k]]
    assert 0.15 < len(moved) / len(KEYS) < 0.25  # ideal is 1/5 = 0.20
    assert all(after[k] == "E" for k in moved)  # nobody else's keys got shuffled


def test_modulo_hashing_moves_most_keys():
    before, after = placement(ModuloRouter(FOUR)), placement(ModuloRouter(FOUR + ["E"]))
    moved = sum(before[k] != after[k] for k in KEYS)
    assert moved / len(KEYS) > 0.75  # the problem consistent hashing solves


def test_removing_a_node_only_moves_that_nodes_keys():
    ring = ConsistentHashRing(FOUR + ["E"], vnodes=150)
    before = placement(ring)
    ring.remove_node("C")
    after = placement(ring)
    assert all(before[k] == "C" for k in KEYS if before[k] != after[k])
    assert "C" not in after.values()


def test_virtual_nodes_improve_balance():
    fair = len(KEYS) / len(FOUR)

    def spread(vnodes: int) -> float:  # std-dev of load, relative to a fair share
        dist = ConsistentHashRing(FOUR, vnodes=vnodes).distribution(KEYS)
        return pstdev(dist[n] for n in FOUR) / fair

    def busiest(vnodes: int) -> float:
        return max(ConsistentHashRing(FOUR, vnodes=vnodes).distribution(KEYS).values()) / fair

    # Any single layout is random (200 vnodes can land worse than 100), so assert the
    # trend and a bound that holds with plenty of vnodes, not one lucky number.
    assert spread(1) > 0.5
    assert spread(500) < 0.06
    assert all(busiest(v) < 1.15 for v in (200, 500, 1000))


def test_weight_scales_ownership():
    ring = ConsistentHashRing(["A", "B"], vnodes=200)
    ring.add_node("BIG", weight=2)
    dist = ring.distribution(KEYS)
    assert 1.6 < dist["BIG"] / ((dist["A"] + dist["B"]) / 2) < 2.4


def test_replicas_are_distinct_physical_nodes():
    ring = ConsistentHashRing(FOUR, vnodes=50)
    for k in KEYS[:500]:
        replicas = ring.get_nodes(k, 3)
        assert len(replicas) == len(set(replicas)) == 3
        assert replicas[0] == ring.get_node(k)  # primary is the clockwise owner
    assert len(ring.get_nodes("x", 10)) == 4  # can't have more replicas than servers


def test_errors():
    with pytest.raises(LookupError):
        ConsistentHashRing().get_node("x")
    ring = ConsistentHashRing(["A"])
    with pytest.raises(ValueError):
        ring.add_node("A")
    with pytest.raises(KeyError):
        ring.remove_node("Z")
