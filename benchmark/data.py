"""Records for the Python reference answers, read from the ETL's NDJSON output"""

from __future__ import annotations

import importlib
import json
from collections import Counter, defaultdict
from pathlib import Path

CHILD_ENTITIES = ("issue", "pull_request", "comment", "review", "link")
QUERIES = ("q0", "q1", "q2", "q3", "q4", "q5", "q6")
REPOS_DIR = Path(__file__).parent / "repos"


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


def repo_sizes(records_dir: Path) -> Counter[int]:
    """Issues, PRs, comments and reviews per repository (the size used to rank)"""
    sizes: Counter[int] = Counter()
    for entity in ("issue", "pull_request", "comment", "review"):
        with open(records_dir / f"{entity}.ndjson") as f:
            for line in f:
                sizes[json.loads(line)["repo_id"]] += 1
    return sizes


def _link_candidates(records_dir: Path) -> set[int]:
    """Repositories with at least one PR-to-issue link.

    Q5 and Q6 can only be informative with such a link, so other repositories
    are skipped before the (slower) reference answers are computed.
    """
    with open(records_dir / "link.ndjson") as f:
        return {r["repo_id"] for r in map(json.loads, f) if r["target_type"] == "issue"}


def pick_repos(records_dir: Path, queries: tuple[str, ...] = QUERIES) -> dict:
    """Pick the small, median and largest repository that every query can use.

    A repository is eligible when every query's reference answer is informative
    (each query module's `informative`). Eligible repositories are ranked by
    size (ties by repo_id) and the first, middle and last are picked.
    """
    sizes = repo_sizes(records_dir)
    candidates = _link_candidates(records_dir)
    data = Records(records_dir, candidates)
    mods = [importlib.import_module(f"benchmark.queries.{q}") for q in queries]
    eligible = sorted(
        (
            (sizes[r], r)
            for r in candidates
            if all(m.informative(m.reference(data, r)) for m in mods)
        ),
    )
    if not eligible:
        raise ValueError("no repository has an informative answer for every query")
    chosen = {
        "small": eligible[0],
        "median": eligible[len(eligible) // 2],
        "largest": eligible[-1],
    }
    return {
        "repos": {label: r for label, (_, r) in chosen.items()},
        "sizes": {label: size for label, (size, _) in chosen.items()},
        "eligible": len(eligible),
        "queries": list(queries),
        "records": str(records_dir),
    }


def picks_path(tier: str) -> Path:
    return REPOS_DIR / f"{tier}.json"


def load_or_pick(tier: str, records_dir: Path, repick: bool = False) -> dict:
    """Read the saved picks for a tier, or pick and save them.

    Saved picks keep every run on the same repositories. Pass repick=True after
    the records change (for example a new ETL run).
    """
    path = picks_path(tier)
    if path.exists() and not repick:
        return json.loads(path.read_text())
    picks = {"tier": tier} | pick_repos(records_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(picks, indent=2) + "\n")
    return picks
