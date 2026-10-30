"""
Testing a rule of thumb: "cache the hottest 20% of items and you serve 80% of reads".

It's true only when popularity is skewed. Real access patterns often follow a Zipf
distribution: the k-th most popular item is requested in proportion to 1 / k^s. With
s ≈ 1, a few items get most of the traffic. With s = 0, every item is equally popular,
and caching 20% of items serves only 20% of reads.
"""
from __future__ import annotations

import bisect
import itertools
import random


def zipf_sampler(n_items: int, s: float, seed: int):
    """Return a function that draws item ranks 0..n-1 (0 = most popular) with P(k) ∝ 1/(k+1)^s."""
    weights = [1 / (k + 1) ** s for k in range(n_items)]
    cumulative = list(itertools.accumulate(weights))
    total, rng = cumulative[-1], random.Random(seed)
    return lambda: bisect.bisect_left(cumulative, rng.random() * total)  # inverse-CDF sampling


def hit_ratio(n_items: int, s: float, cache_fraction: float, requests: int = 200_000, seed: int = 1) -> float:
    """Share of requests that hit a cache holding the most popular `cache_fraction` of items.
    (An ideal cache that already knows the ranking: an upper bound for LRU and friends.)"""
    draw, cached = zipf_sampler(n_items, s, seed), int(n_items * cache_fraction)
    return sum(draw() < cached for _ in range(requests)) / requests
