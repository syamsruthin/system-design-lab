"""
How long one request takes to serve, when nothing is queued: the "service time".

Real services look like this: most requests are fast and similar (a log-normal around 15 ms),
and a small fraction hit something slow (a garbage-collection pause, a cold cache, a disk
read) and take 200–1000 ms. That small fraction is the tail.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable

Sampler = Callable[[], float]  # returns one service time, in seconds


def service_times(seed: int, slow_fraction: float = 0.02, typical_ms: float = 15.0) -> Sampler:
    rng = random.Random(seed)  # seeded: the same "random" latencies on every run

    def sample() -> float:
        if rng.random() < slow_fraction:
            return rng.uniform(0.2, 1.0)
        return rng.lognormvariate(math.log(typical_ms / 1000), 0.4)

    return sample


def mean_service_time(slow_fraction: float, n: int = 200_000, seed: int = 99) -> float:
    """Estimated by sampling. A server with c workers can complete at most c / mean requests per second."""
    sample = service_times(seed, slow_fraction)
    return sum(sample() for _ in range(n)) / n
