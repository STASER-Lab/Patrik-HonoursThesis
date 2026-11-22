"""Write each layout's Elasticsearch bulk files from the entity records"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path

from .mappings import LAYOUTS, S2_COPIED, S2_LINK_COPIED

ID_FIELD = {
    "repository": "repo_id",
    "person": "person_id",
    "issue": "issue_key",
    "pull_request": "pr_key",
    "comment": "comment_id",
    "review": "review_id",
    "link": "link_key",
}

# Entities S2 and S3 combine across records. Each carries repo_id, and every parent
# key lies in the child's repository, so splitting by repo_id keeps families whole.
LINKED = ("issue", "pull_request", "comment", "review", "link")

# Default index.mapping.nested_objects.limit. S3 documents above it are counted, not
# split, and Elasticsearch rejects them at load.
NESTED_LIMIT = 10_000


def read_records(records_dir: Path, entity: str) -> Iterator[dict]:
    with open(records_dir / f"{entity}.ndjson") as f:
        yield from map(json.loads, f)


def copy_parent(child: dict, parent: dict) -> dict:
    return child | {f"parent_{k}": parent.get(k) for k in S2_COPIED}


def copy_link_parents(link: dict, pr: dict, issue: dict | None) -> dict:
    issue = issue or {}
    return (
        link
        | {f"pr_{k}": pr.get(k) for k in S2_LINK_COPIED["pr"]}
        | {f"issue_{k}": issue.get(k) for k in S2_LINK_COPIED["issue"]}
    )


def spill(records_dir: Path, work: Path, buckets: int) -> list[Path]:
    """Split the linked entities into `buckets` gzip directories by repo_id."""
    dirs = [work / str(i) for i in range(buckets)]
    for d in dirs:
        d.mkdir(parents=True)
    for entity in LINKED:
        out = [
            gzip.open(d / f"{entity}.ndjson.gz", "wt", compresslevel=1) for d in dirs
        ]
        try:
            with open(records_dir / f"{entity}.ndjson") as f:
                for line in f:
                    out[json.loads(line)["repo_id"] % buckets].write(line)
        finally:
            for g in out:
                g.close()
    return dirs


def _read_bucket(bucket: Path, entity: str) -> Iterator[dict]:
    with gzip.open(bucket / f"{entity}.ndjson.gz", "rt") as f:
        yield from map(json.loads, f)


def documents(
    layout: str, records_dir: Path, buckets: int = 1, work: Path | None = None
) -> Iterator[tuple[str, str, dict]]:
    """Yield (entity, document id, document) for one layout.

    Document ids are the records' natural keys, so loading twice overwrites rather
    than duplicates. S2 and S3 hold every issue and PR of a bucket in memory. With
    buckets > 1 the linked entities are first spilled to `work` by repo_id and each
    bucket is built alone.
    """
    if layout not in LAYOUTS:
        raise ValueError(layout)
    if buckets < 1:
        raise ValueError("buckets must be at least 1")

    plain = ID_FIELD if layout in ("s1", "s4") else ("repository", "person")
    for entity in plain:
        for r in read_records(records_dir, entity):
            yield entity, str(r[ID_FIELD[entity]]), r
    if layout in ("s1", "s4"):
        return

    if buckets == 1:
        yield from _linked(layout, lambda e: read_records(records_dir, e))
        return
    if work is None:
        raise ValueError("buckets > 1 needs a work directory")
    shutil.rmtree(work, ignore_errors=True)
    try:
        for bucket in spill(records_dir, work, buckets):
            yield from _linked(layout, lambda e, b=bucket: _read_bucket(b, e))
            shutil.rmtree(bucket)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _linked(
    layout: str, read: Callable[[str], Iterator[dict]]
) -> Iterator[tuple[str, str, dict]]:
    """S2 or S3 documents for issues, PRs and their children from one source."""
    issues = {r["issue_key"]: r for r in read("issue")}
    prs = {r["pr_key"]: r for r in read("pull_request")}

    if layout == "s2":
        for entity, table in (("issue", issues), ("pull_request", prs)):
            for k, r in table.items():
                yield entity, k, r
        for c in read("comment"):
            parent = (prs if c["parent_type"] == "pr" else issues)[c["parent_key"]]
            yield "comment", str(c["comment_id"]), copy_parent(c, parent)
        for rv in read("review"):
            yield "review", str(rv["review_id"]), copy_parent(rv, prs[rv["pr_key"]])
        for link in read("link"):
            yield (
                "link",
                link["link_key"],
                copy_link_parents(
                    link, prs[link["pr_key"]], issues.get(link["issue_key"])
                ),
            )
        return

    comments, reviews, links = defaultdict(list), defaultdict(list), defaultdict(list)
    for ln in read("link"):
        links[ln["pr_key"]].append(ln)
    for c in read("comment"):
        comments[c["parent_type"], c["parent_key"]].append(c)
    for rv in read("review"):
        reviews[rv["pr_key"]].append(rv)
    for k, r in issues.items():
        yield "issue", k, s3_issue(r, comments["issue", k])
    for k, r in prs.items():
        yield "pull_request", k, s3_pr(r, comments["pr", k], reviews[k], links[k])


def s3_issue(issue: dict, comments: list[dict]) -> dict:
    """An S3 issue document. Shared by the batch build and the update replay."""
    return issue | {"comments": sorted(comments, key=lambda x: x["created_at"])}


def s3_pr(pr: dict, comments: list, reviews: list, links: list) -> dict:
    """An S3 pull request document. Shared by the batch build and the update replay."""
    return pr | {
        "comments": sorted(comments, key=lambda x: x["created_at"]),
        "reviews": sorted(reviews, key=lambda x: x["submitted_at"]),
        "links": sorted(links, key=lambda x: x["number"]),
    }


def nested_count(doc: dict) -> int:
    return sum(len(doc.get(key, [])) for key in ("comments", "reviews", "links"))


def write_bulk(layout: str, records_dir: Path, out_dir: Path, buckets: int = 1) -> dict:
    out = out_dir / layout
    out.mkdir(parents=True, exist_ok=True)
    files, stats = {}, defaultdict(lambda: {"docs": 0, "bytes": 0})
    nested = {"max_per_doc": 0, "docs_over_limit": 0}
    try:
        for entity, doc_id, doc in documents(
            layout, records_dir, buckets, out / "_buckets"
        ):
            if entity not in files:
                files[entity] = open(out / f"{entity}.ndjson", "w")
            src = json.dumps(doc, ensure_ascii=False)
            files[entity].write(
                json.dumps({"index": {"_id": doc_id}}) + "\n" + src + "\n"
            )
            stats[entity]["docs"] += 1
            stats[entity]["bytes"] += len(src.encode())
            if layout == "s3":
                n = nested_count(doc)
                nested["max_per_doc"] = max(nested["max_per_doc"], n)
                nested["docs_over_limit"] += n > NESTED_LIMIT
    finally:
        for f in files.values():
            f.close()
    summary = {
        "layout": layout,
        "entities": dict(stats),
        "total_docs": sum(s["docs"] for s in stats.values()),
        "total_mb": round(sum(s["bytes"] for s in stats.values()) / 1e6, 1),
    }
    if layout == "s3":
        summary["nested"] = nested
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("records", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/bulk"))
    p.add_argument("--layout", choices=LAYOUTS + ("all",), default="all")
    p.add_argument(
        "--buckets",
        type=int,
        default=1,
        help="build S2/S3 in N repository buckets one at a time to bound memory",
    )
    args = p.parse_args(argv)
    if args.buckets < 1:
        p.error("--buckets must be at least 1")
    for s in LAYOUTS if args.layout == "all" else (args.layout,):
        print(json.dumps(write_bulk(s, args.records, args.out, args.buckets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
