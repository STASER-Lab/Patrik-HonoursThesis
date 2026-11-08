"""Check every strategy's answer against the Python reference"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from benchmark.data import Records, pick_repos

STRATEGIES = ("s1", "s2", "s3", "s4")


def diff(expected, actual, limit: int = 3) -> str:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return f"expected {expected!r}, got {actual!r}"
    missing = [k for k in expected if k not in actual]
    extra = [k for k in actual if k not in expected]
    wrong = [k for k in expected if k in actual and expected[k] != actual[k]]
    parts = [f"{len(expected)} expected keys"]
    if missing:
        parts.append(f"missing {len(missing)} e.g. {missing[:limit]}")
    if extra:
        parts.append(f"extra {len(extra)} e.g. {extra[:limit]}")
    if wrong:
        parts.append(
            f"wrong {len(wrong)} "
            f"e.g. {[(k, expected[k], actual[k]) for k in wrong[:limit]]}"
        )
    return "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tier", default="dev")
    p.add_argument("--records", type=Path, default=Path("data/records"))
    p.add_argument("--queries", default="q1,q2,q3,q4,q5,q6,q7")
    p.add_argument("--q2-keyword", default="security", help="keyword for Q2")
    p.add_argument("--repos", default="auto")
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--env-file", type=Path)
    args = p.parse_args(argv)

    repos = (
        pick_repos(args.records)
        if args.repos == "auto"
        else {f"repo{i}": int(x) for i, x in enumerate(args.repos.split(","))}
    )
    print("Repositories:", repos)
    data = Records(args.records, set(repos.values()))

    from ingest.load.connect import client

    es = client(args.env_file)

    results, failures = [], 0
    for qname in args.queries.split(","):
        q = importlib.import_module(f"bench.queries.{qname}")
        params = {"keyword": args.q2_keyword} if qname == "q2" else {}
        for label, repo_id in repos.items():
            expected = q.reference(data, repo_id, **params)
            size = len(expected)
            for s in args.strategies.split(","):
                row = {
                    "query": qname,
                    "repo": label,
                    "repo_id": repo_id,
                    "strategy": s,
                    "answer_size": size,
                }
                try:
                    start = time.perf_counter()
                    actual, requests = getattr(q, s)(es, args.tier, repo_id, **params)
                    row.update(
                        ms=round((time.perf_counter() - start) * 1000, 1),
                        requests=requests,
                        ok=actual == expected,
                    )
                    if not row["ok"]:
                        row["diff"] = diff(expected, actual)
                except Exception as e:
                    row.update(
                        ok=False,
                        error=f"{type(e).__name__}: {e}",
                        trace=traceback.format_exc(limit=3),
                    )
                failures += not row["ok"]
                status = "PASS" if row["ok"] else "FAIL"
                detail = (
                    row.get("error")
                    or row.get("diff")
                    or f"{row['requests']} req, {row['ms']} ms"
                )
                print(f"{status}  {qname} {label:8} {s} ({size} answers)  {detail}")
                results.append(row)

    out = (
        Path("data/results") / f"check-{args.tier}-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"repos": repos, "results": results}, indent=2))
    print(f"{len(results) - failures}/{len(results)} passed. Saved {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
