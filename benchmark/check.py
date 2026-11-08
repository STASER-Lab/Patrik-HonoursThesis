"""Check every strategy's answer against the Python reference"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from benchmark.data import QUERIES, Records, load_or_pick
from benchmark.queries.common import EsqlRowLimit

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


def environment(es) -> dict:
    info = es.info()
    return {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "elasticsearch_client": importlib.metadata.version("elasticsearch"),
        "elasticsearch_server": info["version"]["number"],
        "elasticsearch_build": info["version"].get("build_hash"),
    }


def run_one(q, strategy: str, es, tier: str, repo_id: int, expected) -> dict:
    row: dict = {}
    try:
        start = time.perf_counter()
        actual, requests = getattr(q, strategy)(es, tier, repo_id)
        row.update(ms=round((time.perf_counter() - start) * 1000, 1), requests=requests)
        if actual == expected:
            row["status"] = "pass"
        else:
            row.update(status="fail", diff=diff(expected, actual))
    except EsqlRowLimit as e:
        row.update(status="limit", error=str(e))
    except Exception as e:
        row.update(
            status="fail",
            error=f"{type(e).__name__}: {e}",
            trace=traceback.format_exc(limit=3),
        )
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tier", default="dev")
    p.add_argument("--records", type=Path, default=Path("data/records"))
    p.add_argument("--queries", default=",".join(QUERIES))
    p.add_argument(
        "--repos",
        default="auto",
        help="'auto' reads benchmark/repos/<tier>.json (picking and saving it "
        "if missing), or a comma-separated list of repo ids",
    )
    p.add_argument(
        "--repick", action="store_true", help="pick repositories again and save"
    )
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--env-file", type=Path)
    args = p.parse_args(argv)

    if args.repos == "auto":
        repos = load_or_pick(args.tier, args.records, args.repick)["repos"]
    else:
        repos = {f"repo{i}": int(x) for i, x in enumerate(args.repos.split(","))}
    print("Repositories:", repos)
    data = Records(args.records, set(repos.values()))

    from ingest.load.connect import client

    es = client(args.env_file)
    env = environment(es)
    print(f"Elasticsearch {env['elasticsearch_server']} ")

    results = []
    for qname in args.queries.split(","):
        q = importlib.import_module(f"benchmark.queries.{qname}")
        for label, repo_id in repos.items():
            expected = q.reference(data, repo_id)
            for s in args.strategies.split(","):
                row = {"query": qname, "repo": label, "repo_id": repo_id, "strategy": s}
                row |= run_one(q, s, es, args.tier, repo_id, expected)
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
    out = (
        Path("data/results") / f"check-{args.tier}-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "tier": args.tier,
                "environment": env,
                "repos": repos,
                "counts": counts,
                "results": results,
            },
            indent=2,
        )
    )
    print(
        f"{counts['pass']} passed, {counts['fail']} failed, "
        f"{counts['limit']} hit the ES|QL row limit. Saved {out}"
    )
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
