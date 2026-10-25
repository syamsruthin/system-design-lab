"""Tests that pin down how latency, throughput and percentiles behave."""
import pytest

from src.aio_service import measure
from src.queue_sim import simulate
from src.stats import percentile, summarize
from src.workload import mean_service_time, service_times


def test_nearest_rank_percentiles():
    samples = list(range(1, 101))  # 1..100
    assert percentile(samples, 50) == 50
    assert percentile(samples, 99) == 99
    assert percentile(samples, 100) == 100
    assert percentile([7.0], 99) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_mean_hides_the_tail():
    sample = service_times(seed=1, slow_fraction=0.02)
    s = summarize([sample() for _ in range(10_000)])
    assert s.p50 < s.mean < s.p90 * 2  # the mean sits above the typical request...
    assert s.p99 > 10 * s.mean  # ...and far below what the unlucky 1% experience


def test_fan_out_turns_a_rare_tail_into_the_common_case():
    sample = service_times(seed=2, slow_fraction=0.02)

    def slow_page_share(n: int, pages: int = 4_000) -> float:
        return sum(any(sample() >= 0.2 for _ in range(n)) for _ in range(pages)) / pages

    assert slow_page_share(1) == pytest.approx(0.02, abs=0.01)
    assert slow_page_share(100) == pytest.approx(1 - 0.98 ** 100, abs=0.03)  # about 87%


def test_latency_rises_sharply_as_load_nears_capacity():
    capacity = 4 / mean_service_time(0.02)
    p50 = {f: simulate(capacity * f, 4, 20_000, service_times(3, 0.02), seed=4).latency.p50 for f in (0.5, 0.9, 0.95)}
    assert p50[0.9] > 5 * p50[0.5]  # flat at half load, steep near capacity
    assert p50[0.95] > 2 * p50[0.9]


def test_throughput_is_capped_at_capacity_however_much_you_send():
    capacity = 4 / mean_service_time(0.02)
    overloaded = simulate(capacity * 1.3, 4, 20_000, service_times(3, 0.02), seed=4)
    assert overloaded.throughput < capacity * 1.05  # you can't get out more than the workers can do
    assert overloaded.utilization > 0.97


def test_littles_law_holds_at_every_load():
    capacity = 4 / mean_service_time(0.02)
    for fraction in (0.25, 0.75, 0.95):
        r = simulate(capacity * fraction, 4, 20_000, service_times(3, 0.02), seed=4)
        assert r.in_system_measured == pytest.approx(r.in_system_little, rel=0.05)  # L = λ × W


def test_closed_loop_load_generator_under_reports_a_stall():
    def slow_share(mode: str) -> float:
        lat = measure(mode, service_times(5, 0.0), workers=4, duration=1.2, rate=100, clients=4, stall=(0.4, 0.4))
        return sum(x > 0.1 for x in lat) / len(lat)

    open_share, closed_share = slow_share("open"), slow_share("closed")
    assert open_share > 0.2  # every user arriving during the stall waited
    assert closed_share < 0.05  # the clients stopped sending, so the stall barely shows
