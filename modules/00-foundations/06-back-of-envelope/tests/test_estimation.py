"""Tests that pin down the arithmetic and the rules of thumb behind estimates."""
import pytest

from src.estimate import human, photo_app
from src.measure import dict_lookup, localhost_round_trip
from src.zipf import hit_ratio


def test_human_formatting_rounds_to_a_couple_of_significant_figures():
    assert human(2_000_000_000) == "2 B"
    assert human(23_148, "/s") == "23 K/s"
    assert human(5.475e16, "B") == "55 PB"
    assert human(1.1e12, "bit/s") == "1.1 Tbit/s"
    assert human(58) == "58"


def test_estimate_chains_its_steps_correctly():
    e = photo_app()
    assert e["photo views / day"] == 50e6 * 40
    assert e["avg read QPS"] == pytest.approx(2e9 / 86_400)
    assert e["peak read QPS"] == pytest.approx(3 * e["avg read QPS"])
    assert e["new storage / day"] == pytest.approx(5e6 * 2e6)  # 10 TB a day


def test_estimates_scale_linearly_with_users():
    small, big = photo_app(dau=10e6), photo_app(dau=20e6)
    for step in ("avg read QPS", "new storage / day", "peak egress bandwidth"):
        assert big[step] == pytest.approx(2 * small[step])


def test_servers_are_sized_for_headroom_not_for_100_percent():
    e = photo_app()
    busy_at_peak = e["peak read QPS"] / (e["app servers at peak"] * 2_000)
    assert 0.5 < busy_at_peak <= 0.6  # the 60% target, after rounding servers up


def test_forgetting_the_peak_overloads_the_fleet():
    naive = photo_app(peak_factor=1)
    true_peak = 3 * naive["avg read QPS"]
    assert true_peak / (naive["app servers at peak"] * 2_000) > 1.5  # far past capacity


def test_80_20_rule_holds_for_zipf_and_fails_for_uniform_traffic():
    assert hit_ratio(20_000, s=1.0, cache_fraction=0.2, requests=50_000) > 0.8
    assert hit_ratio(20_000, s=0.0, cache_fraction=0.2, requests=50_000) == pytest.approx(0.2, abs=0.01)
    assert hit_ratio(20_000, 1.2, 0.2, 50_000) > hit_ratio(20_000, 0.8, 0.2, 50_000)  # more skew, more hits


def test_memory_is_orders_of_magnitude_faster_than_a_network_round_trip():
    assert dict_lookup() < 10e-6  # well under 10 µs
    assert localhost_round_trip() > 50 * dict_lookup()  # even the fastest network hop costs far more
