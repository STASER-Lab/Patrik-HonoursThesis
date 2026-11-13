"""Transform GH Archive hourly files into one NDJSON file per entity"""

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
from .validate import Validator, get


def accepted(
    files: Iterable[Path],
    keep: set[int] | None,
    screen: Screen,
    validate: Validator,
    counts: Counter[str],
) -> Iterator[dict]:
    """Steps 1 to 3. The repository screen runs before validation, so rejection
    counts describe the kept repositories only."""
    for ev in screen(files):
        if keep is not None:
            if (repo_id := get(ev, "repo.id")) is None:
                counts["no_repo_id"] += 1
                continue
            if repo_id not in keep:
                counts["outside_repo_list"] += 1
                continue
        if validate(ev):
            yield ev


def drop_forks(folder: Folder) -> Counter[str]:
    """Remove fork repositories and their records. People are kept: they may be
    active in other repositories."""
    forks = {
        rid: r["events"]
        for rid, r in folder.records["repository"].items()
        if r["is_fork"]
    }
    if forks:
        for entity in ("repository", "issue", "pull_request", "comment", "review"):
            table = folder.records[entity]
            for k in [k for k, r in table.items() if r["repo_id"] in forks]:
                del table[k]
    return Counter(repos=len(forks), events=sum(forks.values()))


def fold(events: Iterable[dict]) -> tuple[Folder, dict, Counter[str]]:
    """Steps 4 and 5. Forks are dropped before linking, so no link enters a fork."""
    folder = Folder()
    for ev in events:
        folder.add(ev)
    forks = drop_forks(folder)
    return folder, add_links(folder), forks


def _authored(folder: Folder) -> Counter[str]:
    return Counter(
        "bot" if r["author_is_bot"] else "human"
        for entity in ("issue", "pull_request", "comment", "review")
        for r in folder.records[entity].values()
    )


def run(
    files: Iterable[Path], keep: set[int] | None, out: Path, buckets: int = 1
) -> dict:
    """Write one NDJSON file per entity to `out` and return the summary.

    Accepted events are spilled to `buckets` files by repository id and each bucket
    is folded alone, so memory holds one bucket. This is exact because no record or
    link spans repositories. People do, so each keeps its latest version across
    buckets.
    """
    screen, validate, counts = Screen(), Validator(), Counter()
    start = time.perf_counter()
    work = out / "buckets"
    work.mkdir(parents=True, exist_ok=True)

    paths = [work / f"{i}.ndjson.gz" for i in range(buckets)]
    spill = [gzip.open(p, "wt", compresslevel=1) for p in paths]
    try:
        for ev in accepted(files, keep, screen, validate, counts):
            spill[ev["repo"]["id"] % buckets].write(json.dumps(ev) + "\n")
    finally:
        for f in spill:
            f.close()

    records, links, authored, forks = Counter(), Counter(), Counter(), Counter()
    people: dict[int, tuple] = {}
    outputs = {e: open(out / f"{e}.ndjson", "w") for e in ENTITIES if e != "person"}
    try:
        for path in paths:
            with gzip.open(path, "rt") as f:
                folder, bucket_links, bucket_forks = fold(map(json.loads, f))
            path.unlink()
            links.update(bucket_links)
            forks.update(bucket_forks)
            authored.update(_authored(folder))
            for entity, f in outputs.items():
                for rec in folder.records[entity].values():
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    records[entity] += 1
            for pid, rec in folder.records["person"].items():
                version = folder.versions[("person", pid)]
                if version >= people.get(pid, (("", -1),))[0]:
                    people[pid] = (version, rec)
    finally:
        for f in outputs.values():
            f.close()
        shutil.rmtree(work)

    with open(out / "person.ndjson", "w") as f:
        for _, rec in people.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    records["person"] = len(people)

    total = authored["bot"] + authored["human"]
    return {
        "seconds": round(time.perf_counter() - start, 1),
        "events_unparseable": screen.counts["unparseable"],
        "events_other_types": screen.counts["other_types"],
        "events_no_repo_id": counts["no_repo_id"],
        "events_outside_repo_list": counts["outside_repo_list"],
        "events_rejected": dict(validate.rejected),
        "events_accepted": validate.accepted,
        "forks_dropped": {"repos": forks["repos"], "events": forks["events"]},
        "records": {e: records[e] for e in ENTITIES},
        "links": dict(links),
        "authored_records": {
            "total": total,
            "bot": authored["bot"],
            "bot_share": round(authored["bot"] / total, 4) if total else None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/records"))
    p.add_argument(
        "--repos", type=Path, help="file of repository ids to keep (one per line)"
    )
    p.add_argument(
        "--buckets",
        type=int,
        default=1,
        help="fold N repository buckets one at a time to bound memory",
    )
    args = p.parse_args(argv)
    if args.buckets < 1:
        p.error("--buckets must be at least 1")

    files = sorted(args.folder.glob("*.json.gz"))
    if not files:
        print(f"No *.json.gz files in {args.folder}", file=sys.stderr)
        return 1
    keep = {int(x) for x in args.repos.read_text().split()} if args.repos else None

    summary = {
        "files": len(files),
        "repo_list": str(args.repos) if args.repos else None,
        "buckets": args.buckets,
        **run(files, keep, args.out, args.buckets),
    }
    text = json.dumps(summary, indent=2)
    (args.out / "summary.json").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
