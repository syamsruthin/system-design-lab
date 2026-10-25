"""
A server with c workers and one FIFO queue, simulated event by event (no real waiting).

Requests arrive at random (a Poisson process: independent arrivals at an average rate λ).
Each one waits for a free worker, then takes its service time. Its latency is queue wait
plus service time, so latency depends on load: the closer the arrival rate gets to the
server's capacity, the longer the queue.

Little's Law ties the three numbers together: L = λ × W
    L  average number of requests in the system (waiting or being served)
    λ  throughput, requests per second
    W  average latency, seconds
"""
from __future__ import annotations

import bisect
import heapq
import random
from dataclasses import dataclass

from .stats import Summary, summarize
from .workload import Sampler


@dataclass
class SimResult:
    offered_rate: float        # arrivals per second we sent
    throughput: float          # completions per second we got
    utilization: float         # fraction of worker time spent serving
    latency: Summary           # seconds, per request
    in_system_measured: float  # L, measured by sampling how many requests were inside
    in_system_little: float    # λ × W, predicted by Little's Law


def simulate(rate: float, workers: int, n: int, service: Sampler, seed: int) -> SimResult:
    rng = random.Random(seed)
    free_at = [0.0] * workers  # min-heap: when each worker next becomes free
    arrivals, finishes, latencies, busy = [], [], [], 0.0
    t = 0.0
    for _ in range(n):
        t += rng.expovariate(rate)  # Poisson arrivals: exponential gaps between them
        start = max(t, heapq.heappop(free_at))  # wait for the earliest free worker (FIFO order)
        work = service()
        heapq.heappush(free_at, start + work)
        arrivals.append(t)
        finishes.append(start + work)
        latencies.append(start + work - t)
        busy += work
    end = max(finishes)
    throughput = n / end

    # Measure L directly: look inside the system at 2,000 moments and count who is there.
    finished_sorted = sorted(finishes)
    moments = [end * (i + 0.5) / 2000 for i in range(2000)]
    inside = [bisect.bisect_right(arrivals, m) - bisect.bisect_right(finished_sorted, m) for m in moments]
    mean_latency = sum(latencies) / n
    return SimResult(rate, throughput, busy / (workers * end), summarize(latencies),
                     sum(inside) / len(inside), throughput * mean_latency)
