"""Reset one layout's indexes to the untouched 2024 state before each replay.

--prepare (once, after loading): write-block each index and clone it to
base-<index>, which stays write-blocked and is never replayed on.
Default (before every repetition): delete the layout's indexes and clone them back
from base-, with no replicas and refresh off. Clones hard-link segment files, so
this takes seconds and little disk.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ingest.load.connect import client
from ingest.load.mappings import LAYOUTS, index_definitions

BASE = "base-"
# Clone keeps the source's settings, including its write block, but not
# number_of_replicas, so both are set on every clone
CLONE_SETTINGS = {
    "index.number_of_replicas": 0,
    "index.refresh_interval": "-1",
    "index.blocks.write": None,
}


def names(layout: str, tier: str) -> list[str]:
    return list(index_definitions(layout, tier))


def _clone(es, source: str, target: str, settings: dict) -> None:
    es.indices.clone(index=source, target=target, settings=settings)
    es.cluster.health(index=target, wait_for_status="green", timeout="10m")


def prepare(es, indexes: list[str]) -> None:
    if existing := [i for i in indexes if es.indices.exists(index=BASE + i)]:
        sys.exit(f"Already prepared: {existing}")
    for i in indexes:
        es.indices.put_settings(index=i, settings={"index.blocks.write": True})
        _clone(es, i, BASE + i, {"index.number_of_replicas": 0})


def reset(es, indexes: list[str]) -> None:
    if missing := [i for i in indexes if not es.indices.exists(index=BASE + i)]:
        sys.exit(f"No base copy for {missing}: run with --prepare first")
    for i in indexes:
        if es.indices.exists(index=i):
            es.indices.delete(index=i)
        _clone(es, BASE + i, i, CLONE_SETTINGS)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--layout", choices=LAYOUTS, required=True)
    p.add_argument("--tier", default="dev")
    p.add_argument("--prepare", action="store_true", help="make the base- copies")
    p.add_argument("--env-file", type=Path)
    args = p.parse_args(argv)

    es = client(args.env_file)
    indexes = names(args.layout, args.tier)
    start = time.perf_counter()
    (prepare if args.prepare else reset)(es, indexes)
    seconds = round(time.perf_counter() - start, 1)
    counts = {i: es.count(index=i)["count"] for i in indexes}
    print(json.dumps({"prepare": args.prepare, "seconds": seconds, "counts": counts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
