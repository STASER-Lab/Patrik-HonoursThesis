"""Measure each layout's index storage as loaded and after force-merging to one segment

Size as loaded depends on when Elasticsearch last merged, so only the merged size is
comparable between layouts and runs. Merging rewrites the indexes. Run this last.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingest.load.connect import client, save_result
from ingest.load.mappings import LAYOUTS, index_definitions


def store_stats(es, indexes: list[str]) -> dict[str, dict]:
    s = es.indices.stats(index=",".join(indexes), metric="store,docs,segments")
    out = {}
    for name in indexes:
        prim = s["indices"][name]["primaries"]
        out[name] = {
            "store_mb": round(prim["store"]["size_in_bytes"] / 1e6, 1),
            "segments": prim["segments"]["count"],
            "lucene_docs": prim["docs"]["count"],
        }
    return out


def measure(es, indexes: list[str], force_merge: bool = True) -> dict[str, dict]:
    before = store_stats(es, indexes)
    if not force_merge:
        return {n: {"as_loaded": before[n]} for n in indexes}
    es.options(request_timeout=3600).indices.forcemerge(
        index=",".join(indexes), max_num_segments=1, wait_for_completion=True
    )
    es.indices.refresh(index=",".join(indexes))
    after = store_stats(es, indexes)
    return {n: {"as_loaded": before[n], "merged": after[n]} for n in indexes}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--layout", choices=LAYOUTS + ("all",), required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--env-file", type=Path)
    p.add_argument("--no-force-merge", action="store_true")
    args = p.parse_args(argv)

    es = client(args.env_file)
    key = "as_loaded" if args.no_force_merge else "merged"
    report = {"tier": args.tier, "layouts": {}}
    for s in LAYOUTS if args.layout == "all" else (args.layout,):
        names = list(index_definitions(s, args.tier))
        m = measure(es, names, force_merge=not args.no_force_merge)
        total = round(sum(v[key]["store_mb"] for v in m.values()), 1)
        report["layouts"][s] = {"indexes": m, f"total_store_mb_{key}": total}
        print(f"{s}: {total:>8} MB ({key})")
        for n, v in m.items():
            a = v["as_loaded"]
            line = f"   {n:24} loaded {a['store_mb']:>7} MB / {a['segments']:>3} seg"
            if "merged" in v:
                line += f"  ->  merged {v['merged']['store_mb']:>7} MB"
            print(line)
    print(f"Saved {save_result(f'storage-{args.tier}', es, report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
