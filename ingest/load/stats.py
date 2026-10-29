"""Measure index storage for one strategy and tier, comparably."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .mappings import STRATEGIES, index_definitions


def store_stats(es, indexes: list[str]) -> dict[str, dict]:
    s = es.indices.stats(index=",".join(indexes), metric="store,docs,segments")
    out = {}
    for name in indexes:
        prim = s["indices"][name]["primaries"]
        out[name] = {"store_mb": round(prim["store"]["size_in_bytes"] / 1e6, 1),
                     "segments": prim["segments"]["count"],
                     "lucene_docs": prim["docs"]["count"]}
    return out


def measure(es, indexes: list[str], force_merge: bool = True) -> dict[str, dict]:
    before = store_stats(es, indexes)
    if not force_merge:
        return {n: {"as_loaded": before[n]} for n in indexes}
    es.options(request_timeout=3600).indices.forcemerge(
        index=",".join(indexes), max_num_segments=1, wait_for_completion=True)
    es.indices.refresh(index=",".join(indexes))
    after = store_stats(es, indexes)
    return {n: {"as_loaded": before[n], "merged": after[n]} for n in indexes}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--strategy", choices=STRATEGIES + ("all",), required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--env-file", type=Path)
    p.add_argument("--no-force-merge", action="store_true")
    args = p.parse_args(argv)

    from .connect import client
    es = client(args.env_file)
    report = {"tier": args.tier, "elasticsearch": es.info()["version"]["number"],
              "measured_at": datetime.now(UTC).isoformat(timespec="seconds"), 
              "strategies": {}}
    for s in (STRATEGIES if args.strategy == "all" else (args.strategy,)):
        names = list(index_definitions(s, args.tier))
        m = measure(es, names, force_merge=not args.no_force_merge)
        key = "as_loaded" if args.no_force_merge else "merged"
        total = round(sum(v[key]["store_mb"] for v in m.values()), 1)
        report["strategies"][s] = {"indexes": m, f"total_store_mb_{key}": total}
        print(f"{s}: {total:>8} MB ({key})")
        for n, v in m.items():
            line = f"   {n:24} loaded "
            f"{v['as_loaded']['store_mb']:>7} MB / "
            f"{v['as_loaded']['segments']:>3} seg"
            if "merged" in v:
                line += f"  ->  merged {v['merged']['store_mb']:>7} MB"
            print(line)
    res = Path("data/results")
    res.mkdir(parents=True, exist_ok=True)
    out = res / f"stats-{args.tier}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
