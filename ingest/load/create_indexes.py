"""Create the indexes for one strategy and tier"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .mappings import STRATEGIES, index_definitions


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--strategy", choices=STRATEGIES + ("all",), required=True)
    p.add_argument("--tier", default="dev", help="e.g. dev, 10gb, 100gb, 1tb")
    p.add_argument("--shards", type=int, default=1)
    p.add_argument("--replicas", type=int, default=0)
    p.add_argument("--env-file", type=Path)
    p.add_argument(
        "--recreate", action="store_true", help="delete existing indexes first"
    )
    p.add_argument("--dump", action="store_true", help="print definitions and exit")
    args = p.parse_args(argv)

    strategies = STRATEGIES if args.strategy == "all" else (args.strategy,)
    defs = {}
    for s in strategies:
        defs |= index_definitions(s, args.tier, args.shards, args.replicas)
    if args.dump:
        print(json.dumps(defs, indent=2))
        return 0

    from .connect import client

    es = client(args.env_file)
    print("Connected to Elasticsearch", es.info()["version"]["number"])
    for name, d in defs.items():
        if es.indices.exists(index=name):
            if not args.recreate:
                print(f"exists   {name} (use --recreate to replace)")
                continue
            es.indices.delete(index=name)
        es.indices.create(index=name, settings=d["settings"], mappings=d["mappings"])
        print(f"created  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
