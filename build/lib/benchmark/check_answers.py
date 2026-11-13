"""Check every layout's answer against the Python reference"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
import traceback
from pathlib import Path

from benchmark.queries.common import EsqlRowLimit
from benchmark.repositories import QUERIES, ReferenceData, load_or_pick
from ingest.load.connect import client, save_result
from ingest.load.mappings import LAYOUTS


def diff(expected, actual, limit: int = 3) -> str:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return f"expected {expected!r}, got {actual!r}"
    missing = [k for k in expected if k not in actual]
    extra = [k for k in actual if k not in expected]
    wrong = [
        (k, expected[k], actual[k])
        for k in expected
        if k in actual and expected[k] != actual[k]
    ]
    parts = [f"{len(expected)} expected keys"]
    for label, items in (("missing", missing), ("extra", extra), ("wrong", wrong)):
        if items:
            parts.append(f"{label} {len(items)} e.g. {items[:limit]}")
    return ". ".join(parts)


def run_one(q, layout: str, es, tier: str, repo_id: int, expected) -> dict:
    """Status is pass, fail, or limit: the layout hit the ES|QL row limit, so it
    cannot answer exactly."""
    try:
        start = time.perf_counter()
        actual, requests = getattr(q, layout)(es, tier, repo_id)
        ms = round((time.perf_counter() - start) * 1000, 1)
        if actual == expected:
            return {"status": "pass", "ms": ms, "requests": requests}
        return {
            "status": "fail",
            "ms": ms,
            "requests": requests,
            "diff": diff(expected, actual),
        }
    except EsqlRowLimit as e:
        return {"status": "limit", "error": str(e)}
    except Exception as e:
        return {
            "status": "fail",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(limit=3),
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tier", default="dev")
    p.add_argument("--records", type=Path, default=Path("data/records"))
    p.add_argument("--queries", default=",".join(QUERIES))
    p.add_argument(
        "--repos",
        default="auto",
        help="'auto' reads benchmark/repositories.json (picking and saving it "
        "if missing), or a comma-separated list of repo ids",
    )
    p.add_argument(
        "--repick", action="store_true", help="pick repositories again and save"
    )
    p.add_argument("--layouts", default=",".join(LAYOUTS))
    p.add_argument("--env-file", type=Path)
    args = p.parse_args(argv)

    if args.repos == "auto":
        repos = load_or_pick(args.tier, args.records, args.repick)["repos"]
    else:
        repos = {f"repo{i}": int(x) for i, x in enumerate(args.repos.split(","))}
    print("Repositories:", repos)
    data = ReferenceData(args.records, set(repos.values()))
    es = client(args.env_file)

    results = []
    for qname in args.queries.split(","):
        q = importlib.import_module(f"benchmark.queries.{qname}")
        for label, repo_id in repos.items():
            expected = q.reference(data, repo_id)
            for s in args.layouts.split(","):
                row = {
                    "query": qname,
                    "repo": label,
                    "repo_id": repo_id,
                    "layout": s,
                    **run_one(q, s, es, args.tier, repo_id, expected),
                }
                detail = (
                    row.get("error")
                    or row.get("diff")
                    or f"{row['requests']} req, {row['ms']} ms"
                )
                print(f"{row['status'].upper():5} {qname} {label:8} {s}  {detail}")
                results.append(row)

    counts = {
        k: sum(r["status"] == k for r in results) for k in ("pass", "fail", "limit")
    }
    out = save_result(
        f"check-{args.tier}",
        es,
        {"tier": args.tier, "repos": repos, "counts": counts, "results": results},
    )
    print(
        f"{counts['pass']} passed, {counts['fail']} failed, "
        f"{counts['limit']} hit the ES|QL row limit. Saved {out}"
    )
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
