"""
Latency, throughput & percentiles: four experiments.

    make run                  # all four (sections 1-3 are simulated and identical every run;
                              # section 4 is real asyncio and varies by a few ms)
    SLOW_PCT=5 make run       # Break it: a heavier tail (5% slow requests instead of 2%)
"""
from __future__ import annotations

import os

from .aio_service import measure
from .queue_sim import simulate
from .stats import histogram, percentile, summarize
from .workload import mean_service_time, service_times

SLOW = float(os.environ.get("SLOW_PCT", 2)) / 100
WORKERS = 4


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def ms(seconds: float) -> str:
    return f"{seconds * 1000:,.1f} ms"


def experiment_percentiles(n: int = 10_000) -> None:
    print(f"\n1) Averages hide the tail: {n:,} requests, {SLOW:.0%} of them hit something slow")
    sample = service_times(seed=1, slow_fraction=SLOW)
    latencies = [sample() for _ in range(n)]
    s = summarize(latencies)
    table(["mean", "p50", "p90", "p99", "p99.9", "max"],
          [[ms(s.mean), ms(s.p50), ms(s.p90), ms(s.p99), ms(s.p999), ms(s.max)]])
    print("\n  latency histogram (log-scaled bars):")
    for label, count, bar in histogram([x * 1000 for x in latencies], [0, 10, 20, 40, 100, 200, 500, 1000]):
        print(f"    {label}  {count:>6,}  {bar}")
    print(f"  → the mean ({ms(s.mean)}) describes no real request: half finished within {ms(s.p50)}, "
          f"and 1 in 100 took {ms(s.p99)} or more.")


def experiment_fan_out(pages: int = 10_000) -> None:
    print(f"\n2) Fan-out: one page waits for N backend calls in parallel (each backend as in section 1)")
    sample = service_times(seed=2, slow_fraction=SLOW)
    rows = []
    for n in (1, 10, 50, 100):
        page_latencies, slow_pages = [], 0
        for _ in range(pages):
            calls = [sample() for _ in range(n)]
            page_latencies.append(max(calls))  # the page is as slow as its slowest call
            slow_pages += any(c >= 0.2 for c in calls)
        rows.append([str(n), ms(percentile(page_latencies, 50)), ms(percentile(page_latencies, 99)),
                     f"{slow_pages / pages:.1%}", f"{1 - (1 - SLOW) ** n:.1%}"])
    table(["backends per page", "page p50", "page p99", "pages hitting a slow call", "1 − (1 − p)^N"], rows)
    print(f"  → each backend is slow only {SLOW:.0%} of the time, but most pages that need 50 or 100 of them are")
    print("    slow. A backend's rare tail becomes the *typical* experience of a page that fans out widely.")


def experiment_load() -> None:
    mean = mean_service_time(SLOW)
    capacity = WORKERS / mean
    print(f"\n3) Latency vs load: {WORKERS} workers, mean service time {ms(mean)} → capacity ≈ {capacity:.0f} req/s "
          f"(simulated, 20,000 requests)")
    rows = []
    for fraction in (0.25, 0.5, 0.75, 0.9, 0.95, 1.05):
        r = simulate(capacity * fraction, WORKERS, 20_000, service_times(seed=3, slow_fraction=SLOW), seed=4)
        rows.append([f"{r.offered_rate:.0f} ({fraction:.0%})", f"{r.throughput:.0f}", f"{r.utilization:.0%}",
                     ms(r.latency.p50), ms(r.latency.p99), f"{r.in_system_measured:.1f}", f"{r.in_system_little:.1f}"])
    table(["offered req/s (load)", "throughput", "busy", "p50", "p99", "L measured", "λ × W"], rows)
    print("  → latency stays flat, then shoots up as load nears capacity: requests start queueing behind each")
    print("    other. Past 100% the queue grows without limit; throughput is capped, only latency keeps rising.")
    print("    And L = λ × W holds at every load (Little's Law): concurrency = throughput × latency.")


def experiment_coordinated_omission(stall_at: float = 0.75, stall_for: float = 0.5, duration: float = 2.0) -> None:
    print(f"\n4) A real asyncio service with {WORKERS} workers freezes once for {stall_for * 1000:.0f} ms. "
          "Two load tests measure it")
    print("   (no random slow requests here, so the stall is the only source of slowness)")
    rows = []
    for mode, label in (("open", "open loop: 100 req/s on a fixed schedule"),
                        ("closed", f"closed loop: {WORKERS} clients, next request after each reply")):
        latencies = measure(mode, service_times(seed=5, slow_fraction=0), WORKERS, duration, rate=100,
                            clients=WORKERS, stall=(stall_at, stall_for))
        s = summarize(latencies)
        slow = sum(x > 0.1 for x in latencies)
        rows.append([label, str(s.count), ms(s.p50), ms(s.p90), ms(s.p99), f"{slow} ({slow / s.count:.0%})"])
    table(["load generator", "requests", "p50", "p90", "p99", "slower than 100 ms"], rows)
    print("  → same server, same stall. The closed-loop clients stopped sending while it was frozen, so only")
    print("    the few requests already in flight saw it. Real users keep arriving, as the open loop does,")
    print("    and every one of them waited. Closed-loop benchmarks under-report the tail.")


if __name__ == "__main__":
    print("=" * 78)
    print(" Latency, throughput & percentiles: tails, fan-out, queueing, measurement")
    print("=" * 78)
    experiment_percentiles()
    experiment_fan_out()
    experiment_load()
    experiment_coordinated_omission()
