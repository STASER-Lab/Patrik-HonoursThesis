"""Build the nested 10 GB, 100 GB and 1 TB tiers as repository lists

Input: the D-004 pool exported from BigQuery (`ingest/sql/tier_pool_2024.sql`),
a CSV with `repo_id,events`. Each tier is filled in four steps (test.md):

1. Filter: already done by the pool query.
2. Sample by size: repositories are split into powers-of-ten bands of events
   (3-9, 10-99, ...). Each band gets the same share of the tier's events as it
   has in the pool, and is filled in a fixed random order until it reaches
   that share (the last repository may overshoot it).
3. Cap the giants: a repository may hold at most 10% of a tier's events.
4. Nest: each tier starts from the smaller one, so it contains all of it.

Output: one `--repos` file per tier (one id per line) and `summary.json` with
the three checks against the pool: median events per repository, share of
events in the top 1% of repositories, and the largest repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

TIERS = {"10gb": 675_000, "100gb": 6_750_000, "1tb": 67_500_000}  # events
CAP = 0.10
SEED = 2024


def band(events: int) -> int:
    return len(str(events)) - 1


def read_pool(path: Path) -> dict[int, int]:
    with open(path, newline="") as f:
        return {int(r["repo_id"]): int(r["events"]) for r in csv.DictReader(f)}


def build(pool: dict[int, int], tiers: dict[str, int], seed: int = SEED) -> dict:
    """Return {tier: set of repo ids}, smallest tier first"""
    order = sorted(pool)
    random.Random(seed).shuffle(order)
    by_band: dict[int, list[int]] = defaultdict(list)
    for rid in order:
        by_band[band(pool[rid])].append(rid)

    chosen: set[int] = set()
    out = {}
    for name, target in sorted(tiers.items(), key=lambda kv: kv[1]):
        cap = CAP * target
        allowed = {b: [r for r in rs if pool[r] <= cap] for b, rs in by_band.items()}
        pool_events = sum(pool[r] for rs in allowed.values() for r in rs)
        if pool_events < target:
            raise ValueError(f"{name}: the pool has only {pool_events} events")
        for b, rs in allowed.items():
            want = target * sum(pool[r] for r in rs) / pool_events
            have = sum(pool[r] for r in chosen if band(pool[r]) == b)
            for r in rs:
                if have >= want:
                    break
                if r not in chosen:
                    chosen.add(r)
                    have += pool[r]
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
    p.add_argument("pool", type=Path, help="CSV from ingest/sql/tier_pool_2024.sql")
    p.add_argument("--out", type=Path, default=Path("ingest/tiers"))
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)

    pool = read_pool(args.pool)
    tiers = build(pool, TIERS, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {
        "pool": {
            "file": args.pool.name,
            "sha256": hashlib.sha256(args.pool.read_bytes()).hexdigest(),
        }
        | describe(list(pool.values())),
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
