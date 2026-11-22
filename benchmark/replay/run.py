"""Replay one layout's derived writes, N events per bulk request, timed.

The timed window is every bulk request plus one refresh at the end (batch mode, as
in index_bulk). Indexes must be fresh clones (reset.py): their counts are checked
against the base- copies first, and against derive's expected counts after.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from ingest.load.connect import client, save_result
from ingest.load.mappings import LAYOUTS

from .reset import BASE


def batches(path: Path, batch_events: int) -> Iterator[tuple[list, int]]:
    """Yield (bulk operations, events) per `batch_events` events. Events with no
    writes count towards the batch, so every layout gets the same event batches."""
    ops, events = [], 0
    with open(path) as f:
        for line in f:
            for op in json.loads(line)["ops"]:
                ops += op  # action dict, then the source as a JSON string
            events += 1
            if events == batch_events:
                yield ops, events
                ops, events = [], 0
    if events:
        yield ops, events


def replay(es, path: Path, indexes: list[str], batch_events: int) -> dict:
    errors, requests = 0, 0
    first_errors: list = []
    events = 0
    start = time.perf_counter()
    for ops, n in batches(path, batch_events):
        events += n
        if not ops:
            continue
        resp = es.bulk(operations=ops, filter_path="errors,items.*.error")
        requests += 1
        for item in resp.get("items", ()):
            if err := next(iter(item.values())).get("error"):
                errors += 1
                if len(first_errors) < 3:
                    first_errors.append(err)
    refresh_start = time.perf_counter()
    es.indices.refresh(index=",".join(indexes))
    end = time.perf_counter()
    return {
        "events": events,
        "requests": requests,
        "errors": errors,
        "first_errors": first_errors,
        "seconds": round(end - start, 2),
        "refresh_seconds": round(end - refresh_start, 2),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--layout", choices=LAYOUTS, required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--writes", type=Path, default=Path("data/replay"))
    p.add_argument("--batch-events", type=int, default=200)
    p.add_argument("--repetition", type=int, default=0)
    p.add_argument("--env-file", type=Path)
    args = p.parse_args(argv)
    if args.batch_events < 1:
        p.error("--batch-events must be at least 1")

    derived = json.loads((args.writes / args.layout / "summary.json").read_text())
    expected = derived["expected_counts"]
    indexes = sorted(expected)
    if not all(i.startswith(f"{args.layout}-{args.tier}-") for i in indexes):
        sys.exit(f"Writes in {args.writes} are not for {args.layout} {args.tier}")

    es = client(args.env_file)
    for i in indexes:
        now, base = (es.count(index=x)["count"] for x in (i, BASE + i))
        if now != base:
            sys.exit(f"{i} has {now} docs, {BASE}{i} has {base}: run reset.py first")

    r = replay(
        es, args.writes / args.layout / "writes.ndjson", indexes, args.batch_events
    )
    es.indices.put_settings(
        index=",".join(indexes), settings={"index": {"refresh_interval": None}}
    )
    counts = {i: es.count(index=i)["count"] for i in indexes}
    count_errors = {i: (counts[i], n) for i, n in expected.items() if counts[i] != n}

    s = r["seconds"]
    per_event = {k: derived[k] for k in ("ops", "docs", "bytes")}
    result = {
        "layout": args.layout,
        "tier": args.tier,
        "repetition": args.repetition,
        "batch_events": args.batch_events,
        **r,
        "events_per_s": round(r["events"] / s, 1) if s else None,
        "ops_per_s": round(per_event["ops"] / s, 1) if s else None,
        "docs_per_s": round(per_event["docs"] / s, 1) if s else None,
        "source_mb_per_s": round(per_event["bytes"] / 1e6 / s, 2) if s else None,
        "write_amplification": {
            k: derived[k]
            for k in ("ops_per_event", "docs_per_event", "bytes_per_event")
        },
        "counts": counts,
        "count_errors": count_errors,
    }
    path = save_result(
        f"replay-{args.layout}-{args.tier}-r{args.repetition}", es, result
    )
    print(
        f"{args.layout}: {r['events']:,} events in {s:.1f} s "
        f"({result['events_per_s'] or 0:,} events/s), {r['errors']} errors, "
        f"{len(count_errors)} count mismatches. Results: {path}"
    )
    return 1 if r["errors"] or count_errors else 0


if __name__ == "__main__":
    sys.exit(main())
