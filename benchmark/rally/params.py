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


def latest_check(
    tier: str, repos: dict[str, int], layouts: tuple[str, ...], results_dir: Path
) -> tuple[Path, dict[tuple[str, str, int], str]]:
    """Newest check_answers result that covers every query, repository and the
    layouts being timed, with its status per (query, layout, repo_id)."""
    needed = {(q, s, r) for q in QUERIES for s in layouts for r in repos.values()}
    for path in sorted(results_dir.glob(f"check-{tier}-*.json"), reverse=True):
        results = json.loads(path.read_text())["results"]
        status = {(x["query"], x["layout"], x["repo_id"]): x["status"] for x in results}
        if needed <= status.keys():
            return path, status
    raise SystemExit(f"No complete check_answers result for tier {tier!r}")


def combinations(
    repos: dict[str, int],
    status: dict[tuple[str, str, int], str],
    layouts: tuple[str, ...],
    repetition: int,
) -> list[dict]:
    failed = sorted(k for k, s in status.items() if s == "fail" and k[1] in layouts)
    if failed:
        raise SystemExit(f"check_answers has failures, not timing them: {failed}")
    return [
        {"query": q, "repo": label, "repo_id": repo_id, "layout": s}
        for q in QUERIES
        for label, repo_id in repos.items()
        for s in rotated(layouts, repetition)
        if status[(q, s, repo_id)] == "pass"
    ]


def mixes(combos: list[dict]) -> dict[str, list[dict]]:
    mix: dict[str, list[dict]] = {}
    for c in combos:
        mix.setdefault(c["layout"], []).append(
            {"query": c["query"], "repo_id": c["repo_id"]}
        )
    return mix


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tier", default="dev")
    p.add_argument("--repetition", type=int, default=0)
    p.add_argument(
        "--layouts",
        default=",".join(LAYOUTS),
        help="comma-separated layouts to time (default: all). Each must be "
        "verified by check_answers",
    )
    p.add_argument("--results", type=Path, default=RESULTS_DIR)
    p.add_argument("--out", type=Path)
    p.add_argument("--warmup", type=int, default=20, help="latency warm-up runs")
    p.add_argument("--iterations", type=int, default=200, help="latency runs")
    p.add_argument("--clients", type=int, default=8, help="throughput clients")
    p.add_argument("--throughput-warmup", type=int, default=60, help="seconds")
    p.add_argument("--throughput-time", type=int, default=180, help="seconds")
    args = p.parse_args(argv)

    layouts = tuple(args.layouts.split(","))
    unknown = [s for s in layouts if s not in LAYOUTS]
    if unknown:
        raise SystemExit(f"Unknown layouts {unknown}, expected some of {LAYOUTS}")

    repos = json.loads(REPOSITORIES_FILE.read_text())[args.tier]["repos"]
    check, status = latest_check(args.tier, repos, layouts, args.results)
    combos = combinations(repos, status, layouts, args.repetition)
    limited = sorted(k for k, s in status.items() if s == "limit" and k[1] in layouts)

    out = args.out or Path(f"data/rally/params-{args.tier}-r{args.repetition}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    order = rotated(layouts, args.repetition)
    track_params = {
        "tier": args.tier,
        "combos": combos,
        "layouts": list(order),
        "mix": mixes(combos),
        "seed": args.repetition,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "clients": args.clients,
        "throughput_warmup": args.throughput_warmup,
        "throughput_time": args.throughput_time,
    }
    out.write_text(json.dumps(track_params, indent=2))
    print(f"Verified by {check}")
    print(f"{len(combos)} combinations, layouts in order {order}")
    if limited:
        print(f"Left out (ES|QL row limit): {limited}")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
