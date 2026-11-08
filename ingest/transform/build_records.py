"""Run transformation on GH Archive files and write one NDJSON file per entity."""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

from .fold import ENTITIES, Folder
from .links import add_links
from .screen import Screen
from .validate import Validator


def accepted(
    files: Iterable[Path],
    keep: set[int] | None,
    screen: Screen,
    validate: Validator,
    counts: Counter[str],
) -> Iterator[dict]:
    """Operations 1 to 3: yield the events that pass screening, tier and validation"""
    for ev in screen(files):
        if keep is not None:
            repo_id = (ev.get("repo") or {}).get("id")
            if repo_id is None:
                counts["no_repo_id"] += 1
                continue
            if repo_id not in keep:
                counts["outside_repo_list"] += 1
                continue
        if validate(ev):
            yield ev


def fold(events: Iterable[dict]) -> tuple[Folder, dict]:
    """Operations 4 and 5: fold events into records, then add links"""
    folder = Folder()
    for ev in events:
        folder.add(ev)
    return folder, add_links(folder)


def _authored(folder: Folder) -> Counter[str]:
    return Counter(
        "bot" if r["author_is_bot"] else "human"
        for entity in ("issue", "pull_request", "comment", "review")
        for r in folder.iter_records(entity)
    )


def _summary(screen, validate, counts, start, records, links, authored) -> dict:
    total = authored["bot"] + authored["human"]
    return {
        "seconds": round(time.time() - start, 1),
        "events_unparseable": screen.counts["unparseable"],
        "events_other_types": screen.counts["other_types"],
        "events_no_repo_id": counts["no_repo_id"],
        "events_outside_repo_list": counts["outside_repo_list"],
        "events_rejected": dict(validate.rejected),
        "events_accepted": validate.accepted,
        "records": dict(records),
        "links": dict(links),
        "authored_records": {
            "total": total,
            "bot": authored["bot"],
            "bot_share": round(authored["bot"] / total, 4) if total else None,
        },
    }


def run(files: Iterable[Path], keep: set[int] | None) -> tuple[Folder, dict]:
    """Fold everything in memory (one bucket)"""
    screen, validate, counts = Screen(), Validator(), Counter()
    start = time.time()
    folder, links = fold(accepted(files, keep, screen, validate, counts))
    summary = _summary(
        screen, validate, counts, start, folder.counts(), links, _authored(folder)
    )
    return folder, summary


def run_bucketed(
    files: Iterable[Path], keep: set[int] | None, out: Path, buckets: int
) -> dict:
    screen, validate, counts = Screen(), Validator(), Counter()
    start = time.time()
    work = out / "buckets"
    work.mkdir(parents=True, exist_ok=True)

    # Spill accepted events to disk, one gzip file per bucket
    paths = [work / f"{i}.ndjson.gz" for i in range(buckets)]
    spill = [gzip.open(p, "wt", compresslevel=1) for p in paths]
    try:
        for ev in accepted(files, keep, screen, validate, counts):
            spill[ev["repo"]["id"] % buckets].write(json.dumps(ev) + "\n")
    finally:
        for f in spill:
            f.close()

    records: Counter[str] = Counter()
    links: Counter[str] = Counter()
    authored: Counter[str] = Counter()
    people: dict[int, tuple] = {}
    outputs = {e: open(out / f"{e}.ndjson", "w") for e in ENTITIES if e != "person"}
    try:
        for path in paths:
            with gzip.open(path, "rt") as f:
                folder, bucket_links = fold(map(json.loads, f))
            path.unlink()
            links.update(bucket_links)
            authored.update(_authored(folder))
            for entity, f in outputs.items():
                for rec in folder.iter_records(entity):
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    records[entity] += 1
            for pid, rec in folder.records["person"].items():
                version = folder.versions[("person", pid)]
                if pid not in people or version >= people[pid][0]:
                    people[pid] = (version, rec)
    finally:
        for f in outputs.values():
            f.close()
    shutil.rmtree(work)

    with open(out / "person.ndjson", "w") as f:
        for _, rec in people.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    records["person"] = len(people)
    records = Counter({e: records[e] for e in ENTITIES})  # keep the usual order
    return _summary(screen, validate, counts, start, records, links, authored)


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
    p.add_argument(
        "--buckets",
        type=int,
        default=1,
        help="fold in N repository buckets on disk to bound memory (1 = in memory)",
    )
    args = p.parse_args(argv)
    if args.buckets < 1:
        p.error("--buckets must be at least 1")

    files = sorted(args.folder.glob("*.json.gz"))
    if not files:
        print(f"No *.json.gz files in {args.folder}", file=sys.stderr)
        return 1
    keep = {int(x) for x in args.repos.read_text().split()} if args.repos else None

    if args.buckets == 1:
        folder, summary = run(files, keep)
        write_records(folder, args.out)
    else:
        summary = run_bucketed(files, keep, args.out, args.buckets)
    summary = {
        "files": len(files),
        "repo_list": str(args.repos) if args.repos else None,
        "buckets": args.buckets,
    } | summary
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
