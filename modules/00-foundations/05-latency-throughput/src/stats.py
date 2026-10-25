"""
Latency statistics from scratch: percentiles, and why the mean is the wrong number to watch.

A percentile answers "how slow is it for the unlucky ones?". p99 = 120 ms means 99% of
requests finished in 120 ms or less, and 1 in 100 took longer. The mean blends a few very
slow requests into many fast ones and describes nobody's actual experience.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def percentile(samples: list[float], p: float) -> float:
    """Nearest-rank percentile: the smallest sample with at least p% of samples at or below it."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = max(1, math.ceil(p / 100 * len(ordered)))  # 1-based rank
    return ordered[rank - 1]


@dataclass
class Summary:
    count: int
    mean: float
    p50: float
    p90: float
    p99: float
    p999: float
    max: float


def summarize(samples: list[float]) -> Summary:
    return Summary(len(samples), sum(samples) / len(samples), percentile(samples, 50), percentile(samples, 90),
                   percentile(samples, 99), percentile(samples, 99.9), max(samples))


def histogram(samples: list[float], edges: list[float], width: int = 40) -> list[tuple[str, int, str]]:
    """Count samples per bucket [edges[i], edges[i+1]) and draw a bar on a log scale, so the rare
    slow buckets stay visible next to the huge fast ones."""
    counts = [0] * (len(edges) - 1)
    for s in samples:
        for i in range(len(edges) - 1):
            if edges[i] <= s < edges[i + 1]:
                counts[i] += 1
                break
    top = math.log10(max(counts) + 1)
    return [(f"{edges[i]:>5.0f}–{edges[i + 1]:<5.0f} ms", c, "█" * round(width * math.log10(c + 1) / top))
            for i, c in enumerate(counts)]
