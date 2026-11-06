"""Records for the Python reference answers, read from the pipeline's NDJSON output"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from benchmark.queries.common import in_window

CHILD_ENTITIES = ("issue", "pull_request", "comment", "review", "link")


class Records:
    def __init__(self, records_dir: Path, repo_ids: set[int]):
        self.by_repo: dict[str, dict[int, list]] = {
            e: defaultdict(list) for e in CHILD_ENTITIES
        }
        for entity in CHILD_ENTITIES:
            with open(records_dir / f"{entity}.ndjson") as f:
                for line in f:
                    r = json.loads(line)
                    if r["repo_id"] in repo_ids:
                        self.by_repo[entity][r["repo_id"]].append(r)

    def records(self, entity: str, repo_id: int) -> list[dict]:
        return self.by_repo[entity].get(repo_id, [])


def pick_repos(records_dir: Path) -> dict[str, int]:
    has_pr: set[int] = set()
    with open(records_dir / "pull_request.ndjson") as f:
        for line in f:
            p = json.loads(line)
            if in_window(p["created_at"]) and not p["author_is_bot"]:
                has_pr.add(p["repo_id"])
    counts: Counter[int] = Counter()
    for entity in ("comment", "review"):
        with open(records_dir / f"{entity}.ndjson") as f:
            for line in f:
                r = json.loads(line)
                if (
                    r["repo_id"] in has_pr
                    and not r["author_is_bot"]
                    and r.get("parent_type", "pr") == "pr"
                ):
                    counts[r["repo_id"]] += 1
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))
    busy = [kv for kv in ranked if kv[1] >= 5] or ranked
    return {
        "small": ranked[0][0],
        "median": busy[len(busy) // 2][0],
        "largest": ranked[-1][0],
    }
