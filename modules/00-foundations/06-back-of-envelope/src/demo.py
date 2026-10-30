"""
Back-of-the-envelope estimation: four experiments.

    make run              # all four (section 1 measures this machine, so its numbers vary)
    PEAK=1 make run       # Break it: estimate from the average and forget the peak
"""
from __future__ import annotations

import os

from .estimate import SECONDS_PER_DAY, human, photo_app
from .measure import run_all
from .zipf import hit_ratio

PEAK = float(os.environ.get("PEAK", 3))
TRUE_PEAK = 3  # how spiky the (pretend) real traffic actually is
SERVER_RPS = 2_000


def table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  " + "  ".join(str(c).ljust(w) for c, w in zip(r, widths))  # noqa: E731
    print(line(headers))
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print(line(r))


def duration(seconds: float) -> str:
    for unit, size in (("s", 1), ("ms", 1e-3), ("µs", 1e-6)):
        if seconds >= size:
            return f"{seconds / size:,.3g} {unit}"
    return f"{seconds / 1e-9:,.3g} ns"


def experiment_machine() -> None:
    print("\n1) This machine's latency numbers (measured now: best of several rounds)")
    results = run_all()
    base = results[0][1]
    rows = [[name, duration(t), f"{t / base:,.0f}×", classic] for name, t, classic in results]
    table(["operation", "measured", "× a dict lookup", "classic table (~2012)"], rows)
    slowest = max(t for _, t, _ in results)
    print(f"  → from {duration(base)} to {duration(slowest)}: a {slowest / base:,.0f}× spread. Estimates need only the order of")
    print("    magnitude, and which step dominates: one truly durable write costs as much as tens of thousands")
    print("    of in-memory lookups, so a design's disk and network steps decide its latency.")


def experiment_approximations() -> None:
    print("\n2) Mental-math shortcuts and how wrong they are")
    rows = []
    for name, exact, approx, approx_text in [
        ("seconds per day", 86_400, 1e5, "10^5"),
        ("seconds per year", 365 * 86_400, 3e7, "3 × 10^7"),
        ("2^10 (KiB)", 2**10, 1e3, "10^3"),
        ("2^30 (GiB)", 2**30, 1e9, "10^9"),
        ("2^40 (TiB)", 2**40, 1e12, "10^12"),
        ("1 M requests/day, per second", 1e6 / SECONDS_PER_DAY, 10, "10 /s"),
    ]:
        rows.append([name, f"{exact:,.0f}" if exact >= 100 else f"{exact:.2f}", approx_text, f"{(approx - exact) / exact:+.1%}"])
    table(["quantity", "exact", "shortcut", "error"], rows)
    print("  → every shortcut is within 25%: harmless when the question is \"1 server or 100?\".")
    print("    Errors of 10× come from wrong assumptions (users, sizes, peaks), not from rounding.")


def experiment_estimate() -> None:
    print(f"\n3) A worked estimate: a photo-sharing app (50 M daily users, peak factor {PEAK:g})")
    e = photo_app(peak_factor=PEAK, server_rps=SERVER_RPS)
    table(["step", "how", "≈"], [[s.name, s.formula, human(s.value, s.unit)] for s in e.steps])
    real_peak = e["avg read QPS"] * TRUE_PEAK
    busy = real_peak / (e["app servers at peak"] * SERVER_RPS)
    print(f"  check: real traffic peaks at {TRUE_PEAK}× average = {human(real_peak, '/s')} → these servers would be "
          f"{busy:.0%} busy")
    storage = human(e["storage, 5 years × 3 copies"], "B")
    egress, image_cache = human(e["peak egress bandwidth"], "bit/s"), human(e["cache 20% of a day's image bytes"], "B")
    meta = human(e["cache 20% of a day's metadata"], "B")
    print(f"  → what the numbers decide: {storage} means object storage, not disks on app servers; {egress} of egress")
    print(f"    and an image cache of {image_cache} mean a CDN serves the photos; {meta} of hot metadata fits in a small")
    print("    cache cluster; and a few dozen app servers are enough. The estimate *is* the architecture sketch.")


def experiment_zipf(n_items: int = 100_000) -> None:
    print(f"\n4) Testing \"cache 20% of items, serve 80% of reads\" ({n_items:,} items, 200,000 requests)")
    rows = []
    for s, shape in ((1.2, "very skewed"), (1.0, "classic Zipf"), (0.8, "milder skew"), (0.5, "weak skew"),
                     (0.0, "uniform: all items equally popular")):
        rows.append([f"{s:g} ({shape})", f"{hit_ratio(n_items, s, 0.01):.0%}", f"{hit_ratio(n_items, s, 0.2):.0%}"])
    table(["Zipf exponent s", "hit ratio, cache 1%", "hit ratio, cache 20%"], rows)
    print("  → the 80/20 rule holds for Zipf-like traffic (s ≈ 1), and fails completely when access is uniform.")
    print("    Measure your skew before you size a cache from a rule of thumb.")


if __name__ == "__main__":
    print("=" * 78)
    print(" Back-of-the-envelope estimation: real latencies, shortcuts, a worked estimate, a rule tested")
    print("=" * 78)
    experiment_machine()
    experiment_approximations()
    experiment_estimate()
    experiment_zipf()
