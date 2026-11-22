"""Offline correctness check for derived replay writes.

Applies each layout's writes to the 2024 documents and compares the result, by
document id and content, with a fresh batch build of the 2024 and window records.
Documents are compared as hashes, so memory holds one small entry per document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from ingest.load.build_bulk import documents
from ingest.load.mappings import LAYOUTS, index_name

NESTED = ("comments", "reviews", "links")
_ID = {"comments": "comment_id", "reviews": "review_id", "links": "link_key"}


def canonical(entity: str, doc: dict) -> dict:
    doc = dict(doc)
    if entity == "repository":
        doc.pop("events", None)
    for k in NESTED:
        if k in doc:  # ties in the batch sort may come out in another order
            doc[k] = sorted(doc[k], key=lambda x, k=k: str(x[_ID[k]]))
    return doc


def digest(entity: str, doc: dict) -> bytes:
    text = json.dumps(canonical(entity, doc), sort_keys=True, ensure_ascii=False)
    return hashlib.blake2b(text.encode(), digest_size=16).digest()


Table = dict[tuple[str, str], tuple[bytes, int | None]]


def table(layout: str, records_dir: Path, tier: str) -> Table:
    return {
        (index_name(layout, tier, e), i): (digest(e, d), d.get("repo_id"))
        for e, i, d in documents(layout, records_dir)
    }


def apply_writes(base: Table, lines: Iterable[dict], forks: set[int]) -> None:
    entity_of = {}
    for line in lines:
        for op in line["ops"]:
            kind, meta = next(iter(op[0].items()))
            k = (meta["_index"], meta["_id"])
            if kind == "delete":
                base.pop(k, None)
                continue
            doc = json.loads(op[1])
            entity = entity_of.setdefault(
                meta["_index"], meta["_index"].split("-", 2)[2]
            )
            base[k] = (digest(entity, doc), doc.get("repo_id"))
            if entity == "repository" and doc.get("is_fork"):
                forks.add(doc["repo_id"])


def compare(layout: str, base_dir: Path, combined_dir: Path, writes: Path, tier: str):
    before = table(layout, base_dir, tier)
    replayed = dict(before)
    forks: set[int] = set()
    with open(writes) as f:
        apply_writes(replayed, map(json.loads, f), forks)
    expected = table(layout, combined_dir, tier)
    person = index_name(layout, tier, "person")
    out = {"layout": layout, "docs": len(replayed), "mismatched": 0, "missing": 0}
    out |= {"extra": 0, "fork_docs_excluded": 0, "base_only_people": 0}
    examples = []
    for k, (h, repo) in replayed.items():
        if repo in forks:
            out["fork_docs_excluded"] += 1
        elif k not in expected:
            if k[0] == person and before.get(k) == (h, repo):
                out["base_only_people"] += 1
            else:
                out["extra"] += 1
                examples.append(("extra", k))
        elif expected[k][0] != h:
            out["mismatched"] += 1
            examples.append(("mismatched", k))
    for k in expected.keys() - replayed.keys():
        out["missing"] += 1
        examples.append(("missing", k))
    out["examples"] = examples[:10]
    out["ok"] = not (out["mismatched"] or out["missing"] or out["extra"])
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", type=Path, default=Path("data/records"))
    p.add_argument("--combined", type=Path, required=True)
    p.add_argument("--writes", type=Path, default=Path("data/replay"))
    p.add_argument("--tier", default="dev")
    p.add_argument("--layout", choices=LAYOUTS + ("all",), default="all")
    args = p.parse_args(argv)
    ok = True
    for s in LAYOUTS if args.layout == "all" else (args.layout,):
        r = compare(
            s, args.base, args.combined, args.writes / s / "writes.ndjson", args.tier
        )
        print(json.dumps(r, default=str))
        ok &= r["ok"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
