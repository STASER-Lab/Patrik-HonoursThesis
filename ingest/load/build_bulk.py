"""Write each layout's Elasticsearch bulk files from the entity records"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterator
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

# Default index.mapping.nested_objects.limit. S3 documents above it are counted, not
# split, and Elasticsearch rejects them at load.
NESTED_LIMIT = 10_000


def read_records(records_dir: Path, entity: str) -> Iterator[dict]:
    with open(records_dir / f"{entity}.ndjson") as f:
        yield from map(json.loads, f)


def _copy_parent(child: dict, parent: dict) -> dict:
    return child | {f"parent_{k}": parent.get(k) for k in S2_COPIED}


def _copy_link_parents(link: dict, pr: dict, issue: dict | None) -> dict:
    issue = issue or {}
    return (
        link
        | {f"pr_{k}": pr.get(k) for k in S2_LINK_COPIED["pr"]}
        | {f"issue_{k}": issue.get(k) for k in S2_LINK_COPIED["issue"]}
    )


def documents(layout: str, records_dir: Path) -> Iterator[tuple[str, str, dict]]:
    """Yield (entity, document id, document) for one layout.

    Document ids are the records' natural keys, so loading twice overwrites rather
    than duplicates. S2 and S3 hold every issue and PR in memory.
    """
    if layout not in LAYOUTS:
        raise ValueError(layout)

    plain = ID_FIELD if layout in ("s1", "s4") else ("repository", "person")
    for entity in plain:
        for r in read_records(records_dir, entity):
            yield entity, str(r[ID_FIELD[entity]]), r
    if layout in ("s1", "s4"):
        return

    issues = {r["issue_key"]: r for r in read_records(records_dir, "issue")}
    prs = {r["pr_key"]: r for r in read_records(records_dir, "pull_request")}

    if layout == "s2":
        for entity, table in (("issue", issues), ("pull_request", prs)):
            for k, r in table.items():
                yield entity, k, r
        for c in read_records(records_dir, "comment"):
            parent = (prs if c["parent_type"] == "pr" else issues)[c["parent_key"]]
            yield "comment", str(c["comment_id"]), _copy_parent(c, parent)
        for rv in read_records(records_dir, "review"):
            yield "review", str(rv["review_id"]), _copy_parent(rv, prs[rv["pr_key"]])
        for link in read_records(records_dir, "link"):
            yield (
                "link",
                link["link_key"],
                _copy_link_parents(
                    link, prs[link["pr_key"]], issues.get(link["issue_key"])
                ),
            )
        return

    comments, reviews, links = defaultdict(list), defaultdict(list), defaultdict(list)
    for ln in read_records(records_dir, "link"):
        links[ln["pr_key"]].append(ln)
    for c in read_records(records_dir, "comment"):
        comments[c["parent_type"], c["parent_key"]].append(c)
    for rv in read_records(records_dir, "review"):
        reviews[rv["pr_key"]].append(rv)
    for k, r in issues.items():
        kids = sorted(comments["issue", k], key=lambda x: x["created_at"])
        yield "issue", k, r | {"comments": kids}
    for k, r in prs.items():
        yield (
            "pull_request",
            k,
            r
            | {
                "comments": sorted(comments["pr", k], key=lambda x: x["created_at"]),
                "reviews": sorted(reviews[k], key=lambda x: x["submitted_at"]),
                "links": sorted(links[k], key=lambda x: x["number"]),
            },
        )


def nested_count(doc: dict) -> int:
    return sum(len(doc.get(key, [])) for key in ("comments", "reviews", "links"))


def write_bulk(layout: str, records_dir: Path, out_dir: Path) -> dict:
    out = out_dir / layout
    out.mkdir(parents=True, exist_ok=True)
    files, stats = {}, defaultdict(lambda: {"docs": 0, "bytes": 0})
    nested = {"max_per_doc": 0, "docs_over_limit": 0}
    try:
        for entity, doc_id, doc in documents(layout, records_dir):
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
    args = p.parse_args(argv)
    for s in LAYOUTS if args.layout == "all" else (args.layout,):
        print(json.dumps(write_bulk(s, args.records, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
