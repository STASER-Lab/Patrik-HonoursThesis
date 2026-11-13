"""Build the nested 10 GB, 100 GB and 1 TB tiers as repository lists.

The input is the pool CSV (`repo_id,events`) from profile/tier_pool_2024.sql.
Repositories are grouped into powers-of-ten bands by event count, and each tier
fills every band, in a fixed random order, up to that band's share of the pool's
events. Each tier contains the smaller one, and no repository may exceed CAP of a
tier's events.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

TIERS = {"10gb": 675_000, "100gb": 6_750_000, "1tb": 67_500_000}  # target events
CAP = 0.10
SEED = 2024


def band(events: int) -> int:
    return len(str(events)) - 1


def read_pool(path: Path) -> dict[int, int]:
    with open(path, newline="") as f:
        return {int(r["repo_id"]): int(r["events"]) for r in csv.DictReader(f)}


def build(pool: dict[int, int], tiers: dict[str, int], seed: int = SEED) -> dict:
    """Return {tier: repository ids}, smallest tier first.

    The repository that fills a band may overshoot its share. Admitting only
    repositories that bring a band closer to its share would never admit the largest
    ones, since a large repository always overshoots its band.
    """
    order = sorted(pool)
    random.Random(seed).shuffle(order)
    by_band: dict[int, list[int]] = defaultdict(list)
    for rid in order:
        by_band[band(pool[rid])].append(rid)

    chosen, have, out = set(), Counter(), {}
    for name, target in sorted(tiers.items(), key=lambda kv: kv[1]):
        cap = CAP * target
        allowed = {b: [r for r in rs if pool[r] <= cap] for b, rs in by_band.items()}
        pool_events = sum(pool[r] for rs in allowed.values() for r in rs)
        if pool_events < target:
            raise ValueError(f"{name}: the pool has only {pool_events} events")
        for b, rs in allowed.items():
            want = target * sum(pool[r] for r in rs) / pool_events
            for r in rs:
                if have[b] >= want:
                    break
                if r not in chosen:
                    chosen.add(r)
                    have[b] += pool[r]
        out[name] = set(chosen)
    return out


def describe(events: list[int]) -> dict:
    events = sorted(events, reverse=True)
    top = max(1, len(events) // 100)
    return {
        "repos": len(events),
        "events": sum(events),
        "median_events": statistics.median(events),
        "top_1pct_share": round(sum(events[:top]) / sum(events), 4),
        "largest": events[0],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pool", type=Path, help="CSV from ingest/profile/tier_pool_2024.sql")
    p.add_argument("--out", type=Path, default=Path("ingest/select"))
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)

    pool = read_pool(args.pool)
    tiers = build(pool, TIERS, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {
        "pool": {
            "file": args.pool.name,
            "sha256": hashlib.sha256(args.pool.read_bytes()).hexdigest(),
            **describe(list(pool.values())),
        },
        "seed": args.seed,
        "cap": CAP,
        "tiers": {},
    }
    for name, repos in tiers.items():
        (args.out / f"{name}.txt").write_text("".join(f"{r}\n" for r in sorted(repos)))
        summary["tiers"][name] = {"target_events": TIERS[name]} | describe(
            [pool[r] for r in repos]
        )
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
