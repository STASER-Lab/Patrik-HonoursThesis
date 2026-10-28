"""Run transformation on GH Archive files and write one NDJSON file per entity."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .fold import ENTITIES, Folder
from .links import add_links
from .screen import Screen
from .validate import Validator


def run(files: Iterable[Path], keep: set[int] | None) -> tuple[Folder, dict]:
    screen, validate, folder = Screen(), Validator(), Folder()
    counts: Counter[str] = Counter()
    start = time.time()
    # Operation 1: yields only parsed events of the five types
    for ev in screen(files):
        # Operation 2: tier check, before validation, and safe on broken events
        if keep is not None:
            repo_id = (ev.get("repo") or {}).get("id")
            if repo_id is None:
                counts["no_repo_id"] += 1
                continue
            if repo_id not in keep:
                counts["outside_repo_list"] += 1
                continue
        # Operation 3: validate the event and reject malformed events
        if not validate(ev):
            continue
        # Operation 4: fold the event into the entity records
        folder.add(ev)

    # Operation 5: add links between issues and pull requests
    link_stats = add_links(folder)

    summary = {
        "seconds": round(time.time() - start, 1),
        "events_unparseable": screen.counts["unparseable"],
        "events_other_types": screen.counts["other_types"],
        "events_no_repo_id": counts["no_repo_id"],
        "events_outside_repo_list": counts["outside_repo_list"],
        "events_rejected": dict(validate.rejected),
        "events_accepted": validate.accepted,
        "records": folder.counts(),
        "links": link_stats,
    }
    return folder, summary


def write_records(folder: Folder, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for entity in ENTITIES:
        with open(out / f"{entity}.ndjson", "w") as f:
            for rec in folder.iter_records(entity):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/records"))
    p.add_argument(
        "--repos", type=Path, help="file of repository ids to keep (one per line)"
    )
    args = p.parse_args(argv)

    files = sorted(args.folder.glob("*.json.gz"))
    if not files:
        print(f"No *.json.gz files in {args.folder}", file=sys.stderr)
        return 1
    keep = {int(x) for x in args.repos.read_text().split()} if args.repos else None

    folder, summary = run(files, keep)
    summary = {
        "files": len(files),
        "repo_list": str(args.repos) if args.repos else None,
    } | summary
    write_records(folder, args.out)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
