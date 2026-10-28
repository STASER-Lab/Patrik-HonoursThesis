"""Turn entity records into Elasticsearch bulk files, one set per strategy"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from .mappings import S2_COPIED, S2_LINK_COPIED, STRATEGIES

ID_FIELD = {
    "repository": "repo_id",
    "person": "person_id",
    "issue": "issue_key",
    "pull_request": "pr_key",
    "comment": "comment_id",
    "review": "review_id",
    "link": "link_key",
}

NESTED_LIMIT = 10_000  # Elasticsearch default index.mapping.nested_objects.limit


def read_records(records_dir: Path, entity: str) -> Iterator[dict]:
    with open(records_dir / f"{entity}.ndjson") as f:
        for line in f:
            yield json.loads(line)


def _copy_parent(child: dict, parent: dict) -> dict:
    return child | {f"parent_{k}": parent.get(k) for k in S2_COPIED}


def _copy_link_parents(link: dict, pr: dict, issue: dict | None) -> dict:
    issue = issue or {}
    return (link | {f"pr_{k}": pr.get(k) for k in S2_LINK_COPIED["pr"]}
                 | {f"issue_{k}": issue.get(k) for k in S2_LINK_COPIED["issue"]})


def documents(strategy: str, records_dir: Path) -> Iterator[tuple[str, str, dict]]:
    """Yield (entity, doc_id, document) for one strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(strategy)
    rd = records_dir

    # entities that are identical in every strategy
    for entity in ("repository", "person"):
        for r in read_records(rd, entity):
            yield entity, str(r[ID_FIELD[entity]]), r

    if strategy in ("s1", "s4"):
        for entity in ("issue", "pull_request", "comment", "review", "link"):
            for r in read_records(rd, entity):
                yield entity, str(r[ID_FIELD[entity]]), r
        return

    issues = {r["issue_key"]: r for r in read_records(rd, "issue")}
    prs = {r["pr_key"]: r for r in read_records(rd, "pull_request")}

    if strategy == "s2":
        for entity, table in (("issue", issues), ("pull_request", prs)):
            for k, r in table.items():
                yield entity, k, r
        for c in read_records(rd, "comment"):
            parent = (prs if c["parent_type"] == "pr" else issues)[c["parent_key"]]
            yield "comment", str(c["comment_id"]), _copy_parent(c, parent)
        for rv in read_records(rd, "review"):
            yield "review", str(rv["review_id"]), _copy_parent(rv, prs[rv["pr_key"]])
        for link in read_records(rd, "link"):
            yield (
                "link",
                link["link_key"],
                _copy_link_parents(
                    link, prs[link["pr_key"]], issues.get(link["issue_key"])
                ),
            )
        return

    comments: dict[str, list] = defaultdict(list)
    reviews: dict[str, list] = defaultdict(list)
    links: dict[str, list] = defaultdict(list)
    for ln in read_records(rd, "link"):
        links[ln["pr_key"]].append(ln)
    for c in read_records(rd, "comment"):
        comments[(c["parent_type"], c["parent_key"])].append(c)
    for rv in read_records(rd, "review"):
        reviews[rv["pr_key"]].append(rv)
    for k, r in issues.items():
        kids = sorted(comments.get(("issue", k), []), key=lambda x: x["created_at"])
        yield "issue", k, r | {"comments": kids}
    for k, r in prs.items():
        yield (
            "pull_request",
            k,
            r
            | {
                "comments": sorted(
                    comments.get(("pr", k), []), key=lambda x: x["created_at"]
                ),
                "reviews": sorted(reviews.get(k, []), key=lambda x: x["submitted_at"]),
                "links": sorted(links.get(k, []), key=lambda x: x["number"]),
            },
        )


def nested_count(doc: dict) -> int:
    return sum(len(doc.get(key, [])) for key in ("comments", "reviews", "links"))


def write_bulk(strategy: str, records_dir: Path, out_dir: Path) -> dict:
    out = out_dir / strategy
    out.mkdir(parents=True, exist_ok=True)
    files, stats = {}, defaultdict(lambda: {"docs": 0, "bytes": 0})
    nested = {"max_per_doc": 0, "docs_over_limit": 0}
    try:
        for entity, doc_id, doc in documents(strategy, records_dir):
            if entity not in files:
                files[entity] = open(out / f"{entity}.ndjson", "w")
            src = json.dumps(doc, ensure_ascii=False)
            files[entity].write(
                json.dumps({"index": {"_id": doc_id}}) + "\n" + src + "\n"
            )
            stats[entity]["docs"] += 1
            stats[entity]["bytes"] += len(src.encode())
            if strategy == "s3":
                n = nested_count(doc)
                nested["max_per_doc"] = max(nested["max_per_doc"], n)
                nested["docs_over_limit"] += n > NESTED_LIMIT
    finally:
        for f in files.values():
            f.close()
    summary = {
        "strategy": strategy,
        "entities": dict(stats),
        "total_docs": sum(s["docs"] for s in stats.values()),
        "total_mb": round(sum(s["bytes"] for s in stats.values()) / 1e6, 1),
    }
    if strategy == "s3":
        summary["nested"] = nested
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("records", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/bulk"))
    p.add_argument("--strategy", choices=STRATEGIES + ("all",), default="all")
    args = p.parse_args(list(argv) if argv is not None else None)
    for s in STRATEGIES if args.strategy == "all" else (args.strategy,):
        print(json.dumps(write_bulk(s, args.records, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
