"""Write Rally's track parameters for one tier and one repetition"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.repositories import QUERIES, REPOSITORIES_FILE
from ingest.load.connect import RESULTS_DIR
from ingest.load.mappings import LAYOUTS


def rotated(layouts: tuple[str, ...], repetition: int) -> tuple[str, ...]:
    k = repetition % len(layouts)
    return layouts[k:] + layouts[:k]


def latest_check(tier: str, repos: dict[str, int], results_dir: Path) -> Path:
    needed = {(q, s, r) for q in QUERIES for s in LAYOUTS for r in repos.values()}
    for path in sorted(results_dir.glob(f"check-{tier}-*.json"), reverse=True):
        results = json.loads(path.read_text())["results"]
        if needed <= {(x["query"], x["layout"], x["repo_id"]) for x in results}:
            return path
    raise SystemExit(f"No complete check_answers result for tier {tier!r}")


def statuses(check: Path) -> dict[tuple[str, str, int], str]:
    results = json.loads(check.read_text())["results"]
    return {(x["query"], x["layout"], x["repo_id"]): x["status"] for x in results}


def combinations(
    repos: dict[str, int], status: dict[tuple[str, str, int], str], repetition: int
) -> list[dict]:
    failed = sorted(k for k, s in status.items() if s == "fail")
    if failed:
        raise SystemExit(f"check_answers has failures, not timing them: {failed}")
    return [
        {"query": q, "repo": label, "repo_id": repo_id, "layout": s}
        for q in QUERIES
        for label, repo_id in repos.items()
        for s in rotated(LAYOUTS, repetition)
        if status[(q, s, repo_id)] == "pass"
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tier", default="dev")
    p.add_argument("--repetition", type=int, default=0)
    p.add_argument("--results", type=Path, default=RESULTS_DIR)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    repos = json.loads(REPOSITORIES_FILE.read_text())[args.tier]["repos"]
    check = latest_check(args.tier, repos, args.results)
    status = statuses(check)
    combos = combinations(repos, status, args.repetition)
    limited = sorted(k for k, s in status.items() if s == "limit")

    out = args.out or Path(f"data/rally/params-{args.tier}-r{args.repetition}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tier": args.tier, "combos": combos}, indent=2))
    print(f"Verified by {check}")
    order = rotated(LAYOUTS, args.repetition)
    print(f"{len(combos)} combinations, layouts in order {order}")
    if limited:
        print(f"Left out (ES|QL row limit): {limited}")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
