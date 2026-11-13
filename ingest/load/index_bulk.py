"""Create one layout's indexes and load its bulk files in fixed-size batches, timed

Only the bulk requests are timed. Indexes must not already hold documents, because
loading into them would time updates rather than inserts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .connect import client, save_result
from .mappings import LAYOUTS, index_definitions, index_name


def batches(path: Path, batch_docs: int):
    """Yield (operations, source bytes) per `batch_docs` documents. The file must
    alternate action and source lines."""
    ops, nbytes = [], 0
    with open(path) as f:
        for action, source in zip(f, f, strict=True):
            ops += [json.loads(action), json.loads(source)]
            nbytes += len(source.encode()) - 1
            if len(ops) == 2 * batch_docs:
                yield ops, nbytes
                ops, nbytes = [], 0
    if ops:
        yield ops, nbytes


def create_indexes(es, defs: dict, recreate: bool) -> None:
    for name, d in defs.items():
        if es.indices.exists(index=name):
            if not recreate:
                sys.exit(f"{name} already exists (use --recreate to replace it)")
            es.indices.delete(index=name)
        es.indices.create(index=name, settings=d["settings"], mappings=d["mappings"])


def load_index(es, index: str, path: Path, batch_docs: int) -> dict:
    docs = errors = nbytes = 0
    first_errors: list = []
    start = time.perf_counter()
    for ops, b in batches(path, batch_docs):
        resp = es.bulk(index=index, operations=ops, filter_path="errors,items.*.error")
        docs += len(ops) // 2
        nbytes += b
        for item in resp.get("items", ()):
            if err := next(iter(item.values())).get("error"):
                errors += 1
                if len(first_errors) < 3:
                    first_errors.append(err)
    seconds = time.perf_counter() - start
    mb = nbytes / 1e6
    return {
        "index": index,
        "docs": docs,
        "errors": errors,
        "first_errors": first_errors,
        "seconds": round(seconds, 2),
        "docs_per_s": round(docs / seconds) if seconds else None,
        "source_mb": round(mb, 1),
        "source_mb_per_s": round(mb / seconds, 2) if seconds else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--layout", choices=LAYOUTS, required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--bulk-dir", type=Path, default=Path("data/bulk"))
    p.add_argument("--batch-docs", type=int, default=1000)
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--replicas", type=int, default=0)
    p.add_argument("--env-file", type=Path)
    p.add_argument("--recreate", action="store_true", help="replace existing indexes")
    args = p.parse_args(argv)

    files = sorted((args.bulk_dir / args.layout).glob("*.ndjson"))
    defs = index_definitions(args.layout, args.tier, args.shards, args.replicas)
    plan = [(index_name(args.layout, args.tier, f.stem), f) for f in files]
    for idx, path in plan:
        if idx not in defs:
            sys.exit(f"{path} has no index in layout {args.layout}")

    es = client(args.env_file)
    create_indexes(es, defs, args.recreate)
    results = []
    for idx, path in plan:
        r = load_index(es, idx, path, args.batch_docs)
        print(
            f"{r['index']:30} {r['docs']:>9,} docs {r['seconds']:>8.1f} s "
            f"{r['docs_per_s'] or 0:>8,} docs/s errors {r['errors']}"
        )
        results.append(r)

    es.indices.refresh(index=",".join(defs))
    for r in results:
        r["docs_counted"] = es.count(index=r["index"])["count"]

    total_docs = sum(r["docs"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    path = save_result(
        f"load-{args.layout}-{args.tier}",
        es,
        {
            "layout": args.layout,
            "tier": args.tier,
            "batch_docs": args.batch_docs,
            "shards": args.shards,
            "replicas": args.replicas,
            "indexes": results,
            "total_docs": total_docs,
            "total_errors": total_errors,
            "total_source_mb": round(sum(r["source_mb"] for r in results), 1),
        },
    )
    print(f"Total {total_docs:,} docs, {total_errors} errors. Results: {path}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
