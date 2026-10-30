"""
Back-of-the-envelope estimation as code: a chain of small, named steps, each one a
formula you could do in your head, with every number rounded for humans.

The point of an estimate is the *order of magnitude* (is it 1 server or 1,000? 10 GB or
10 PB?) and the *reasoning*, written down so anyone can check each step and change an
assumption. Precision beyond about 2 significant figures is noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SECONDS_PER_DAY = 86_400   # ≈ 10^5 in your head (16% high, fine for estimates)
DAYS_PER_YEAR = 365


def human(value: float, unit: str = "") -> str:
    """1_234_567 → '1.2 M', 3.4e12 bytes → '3.4 TB'. Decimal (powers of 1,000) on purpose."""
    prefixes = ["", "K", "M", "G", "T", "P"] if unit in ("B", "bit/s") else ["", "K", "M", "B", "T", "P"]
    i = 0
    while abs(value) >= 1000 and i < len(prefixes) - 1:
        value, i = value / 1000, i + 1
    text = f"{value:.2g}" if value < 10 else f"{value:.0f}"
    suffix = f"{prefixes[i]}{unit}"
    return f"{text} {suffix}".strip() if suffix else text


@dataclass
class Step:
    name: str
    formula: str
    value: float
    unit: str


@dataclass
class Estimate:
    title: str
    steps: list[Step] = field(default_factory=list)

    def add(self, name: str, formula: str, value: float, unit: str = "") -> float:
        self.steps.append(Step(name, formula, value, unit))
        return value  # so steps chain: later steps use earlier values

    def __getitem__(self, name: str) -> float:
        return next(s.value for s in self.steps if s.name == name)


def photo_app(dau: float = 50e6, views_per_user: float = 40, upload_every_days: float = 10,
              photo_bytes: float = 2e6, peak_factor: float = 3, replicas: int = 3, years: int = 5,
              hot_fraction: float = 0.2, meta_bytes: float = 500, server_rps: float = 2_000,
              target_utilization: float = 0.6) -> Estimate:
    """Estimate the core numbers for an Instagram-like photo app from a handful of assumptions."""
    e = Estimate("Photo-sharing app")
    reads = e.add("photo views / day", "DAU × views per user", dau * views_per_user)
    writes = e.add("uploads / day", "DAU ÷ days between uploads", dau / upload_every_days)
    read_qps = e.add("avg read QPS", "views/day ÷ 86,400", reads / SECONDS_PER_DAY, "/s")
    e.add("avg write QPS", "uploads/day ÷ 86,400", writes / SECONDS_PER_DAY, "/s")
    peak = e.add("peak read QPS", f"avg × peak factor {peak_factor:g}", read_qps * peak_factor, "/s")
    daily = e.add("new storage / day", "uploads × photo size", writes * photo_bytes, "B")
    e.add(f"storage, {years} years × {replicas} copies", f"per day × 365 × {years} × {replicas}",
          daily * DAYS_PER_YEAR * years * replicas, "B")
    e.add("peak egress bandwidth", "peak read QPS × photo size", peak * photo_bytes * 8, "bit/s")
    # The textbook rule "cache 20% of a day's reads" on the image bytes: far too big for RAM,
    # which is the estimate telling you that image bytes belong in a CDN, not an app cache.
    e.add(f"cache {hot_fraction:.0%} of a day's image bytes", f"views/day × photo size × {hot_fraction}",
          reads * photo_bytes * hot_fraction, "B")
    e.add(f"cache {hot_fraction:.0%} of a day's metadata", f"views/day × {human(meta_bytes, 'B')} × {hot_fraction}",
          reads * meta_bytes * hot_fraction, "B")
    # Size for a utilization target, not 100%: near capacity, queueing makes latency explode
    # (see the latency lesson). 60% busy at peak leaves room for bursts and a lost server.
    per_server = server_rps * target_utilization
    e.add("app servers at peak", f"peak QPS ÷ ({human(server_rps)} req/s × {target_utilization:.0%} busy), rounded up",
          -(-peak // per_server), "")
    return e
