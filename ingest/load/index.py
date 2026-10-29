"""Load bulk files into Elasticsearch in fixed-size batches, measuring throughput."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .mappings import STRATEGIES, index_definitions, index_name


def batches(path: Path, batch_docs: int):
    ops, nbytes = [], 0
    with open(path) as f:
        for action in f:
            source = next(f)
            ops.append(json.loads(action))
            ops.append(json.loads(source))
            nbytes += len(source.encode()) - 1
            if len(ops) == 2 * batch_docs:
                yield ops, nbytes
                ops, nbytes = [], 0
    if ops:
        yield ops, nbytes


def load_index(es, index: str, path: Path, batch_docs: int) -> dict:
    docs = errors = nbytes = 0
    first_errors: list = []
    start = time.perf_counter()
    for ops, b in batches(path, batch_docs):
        resp = es.bulk(index=index, operations=ops, filter_path="errors,items.*.error")
        docs += len(ops) // 2
        nbytes += b
        if resp.get("errors"):
            for item in resp["items"]:
                err = next(iter(item.values())).get("error")
                if err:
                    errors += 1
                    if len(first_errors) < 3:
                        first_errors.append(err)
    seconds = time.perf_counter() - start
    return {
        "index": index,
        "docs": docs,
        "errors": errors,
        "first_errors": first_errors,
        "seconds": round(seconds, 2),
        "docs_per_s": round(docs / seconds) if seconds else None,
        "source_mb": round(nbytes / 1e6, 1),
        "source_mb_per_s": round(nbytes / 1e6 / seconds, 2) if seconds else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--strategy", choices=STRATEGIES, required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--bulk-dir", type=Path, default=Path("data/bulk"))
    p.add_argument("--batch-docs", type=int, default=1000)
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--replicas", type=int, default=0)
    p.add_argument("--env-file", type=Path)
    p.add_argument(
        "--recreate", action="store_true", help="delete and recreate the indexes first"
    )
    args = p.parse_args(argv)

    from .connect import client

    es = client(args.env_file)
    info = es.info()
    defs = index_definitions(args.strategy, args.tier, args.shards, args.replicas)
    if args.recreate:
        for name, d in defs.items():
            es.options(ignore_status=404).indices.delete(index=name)
            es.indices.create(
                index=name, settings=d["settings"], mappings=d["mappings"]
            )

    results = []
    for path in sorted((args.bulk_dir / args.strategy).glob("*.ndjson")):
        index = index_name(args.strategy, args.tier, path.stem)
        if index not in defs:
            print(
                f"skip {path.name}: no index {index} in strategy {args.strategy}",
                file=sys.stderr,
            )
            continue
        r = load_index(es, index, path, args.batch_docs)
        print(
            f"{index:30} {r['docs']:>9,} docs "
            f"{r['seconds']:>8.1f} s "
            f"{r['docs_per_s'] or 0:>8,} docs/s "
            f"errors {r['errors']}"
        )
        results.append(r)

    es.indices.refresh(index=",".join(r["index"] for r in results))
    stats = es.indices.stats(
        index=",".join(r["index"] for r in results), metric="store,docs"
    )
    for r in results:
        prim = stats["indices"][r["index"]]["primaries"]
        r["store_mb"] = round(prim["store"]["size_in_bytes"] / 1e6, 1)
        r["docs_counted"] = prim["docs"][
            "count"
        ]

    out = {
        "strategy": args.strategy,
        "tier": args.tier,
        "batch_docs": args.batch_docs,
        "shards": args.shards,
        "replicas": args.replicas,
        "elasticsearch": info["version"]["number"],
        "host": platform.node(),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "indexes": results,
        "total_docs": sum(r["docs"] for r in results),
        "total_errors": sum(r["errors"] for r in results),
        "total_store_mb": round(sum(r["store_mb"] for r in results), 1),
        "total_source_mb": round(sum(r["source_mb"] for r in results), 1),
    }
    res_dir = Path("data/results")
    res_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = res_dir / f"load-{args.strategy}-{args.tier}-{stamp}.json"
    path.write_text(json.dumps(out, indent=2))
    print(
        f"Total {out['total_docs']:,} docs, {out['total_errors']} errors, "
        f"store {out['total_store_mb']} MB from {out['total_source_mb']} MB source. "
        f"Results: {path}"
    )
    return 1 if out["total_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
