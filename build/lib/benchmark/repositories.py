"""Reference data, and the fixed repositories each tier's queries ask about"""

from __future__ import annotations

import importlib
import json
from collections import defaultdict
from pathlib import Path

from ingest.load.build_bulk import read_records

CHILD_ENTITIES = ("issue", "pull_request", "comment", "review", "link")
QUERIES = ("q1", "q2", "q3", "q4", "q5", "q6", "q7")
REPOSITORIES_FILE = Path(__file__).with_suffix(".json")


class ReferenceData:
    """Records of `repo_ids` only, by entity and repository"""

    def __init__(self, records_dir: Path, repo_ids: set[int]):
        self.by_repo: dict[str, dict[int, list]] = {
            e: defaultdict(list) for e in CHILD_ENTITIES
        }
        for entity in CHILD_ENTITIES:
            for r in read_records(records_dir, entity):
                if r["repo_id"] in repo_ids:
                    self.by_repo[entity][r["repo_id"]].append(r)

    def records(self, entity: str, repo_id: int) -> list[dict]:
        return self.by_repo[entity][repo_id]


def repo_sizes(records_dir: Path) -> dict[int, int]:
    return {r["repo_id"]: r["events"] for r in read_records(records_dir, "repository")}


def _link_candidates(records_dir: Path) -> set[int]:
    """Repositories with a PR-to-issue link: only these can be informative for Q6
    and Q7"""
    return {
        r["repo_id"]
        for r in read_records(records_dir, "link")
        if r["target_type"] == "issue"
    }


def pick_repos(records_dir: Path, queries: tuple[str, ...] = QUERIES) -> dict:
    """The small, median and largest repository, by events, that is informative for
    every query"""
    sizes = repo_sizes(records_dir)
    candidates = _link_candidates(records_dir)
    data = ReferenceData(records_dir, candidates)
    mods = [importlib.import_module(f"benchmark.queries.{q}") for q in queries]
    eligible = sorted(
        (
            r
            for r in candidates
            if all(m.informative(m.reference(data, r)) for m in mods)
        ),
        key=lambda r: (sizes[r], r),
    )
    if not eligible:
        raise ValueError("no repository has an informative answer for every query")
    chosen = {
        "small": eligible[0],
        "median": eligible[len(eligible) // 2],
        "largest": eligible[-1],
    }
    return {
        "repos": chosen,
        "sizes": {label: sizes[r] for label, r in chosen.items()},
        "eligible": len(eligible),
        "queries": list(queries),
        "records": str(records_dir),
    }


def load_or_pick(tier: str, records_dir: Path, repick: bool = False) -> dict:
    """Read the saved repositories for `tier`, or pick and save them. Saved picks
    keep every run on the same repositories. Repick after the tier's records change."""
    saved = (
        json.loads(REPOSITORIES_FILE.read_text()) if REPOSITORIES_FILE.exists() else {}
    )
    if tier in saved and not repick:
        return saved[tier]
    saved[tier] = pick_repos(records_dir)
    REPOSITORIES_FILE.write_text(json.dumps(saved, indent=2) + "\n")
    return saved[tier]
