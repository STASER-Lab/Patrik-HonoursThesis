"""Transform step 5: Add PR-to-issue links from closing keywords"""

from __future__ import annotations

import re
from collections import Counter

KEYWORDS = {
    "close": "close",
    "closes": "close",
    "closed": "close",
    "fix": "fix",
    "fixes": "fix",
    "fixed": "fix",
    "resolve": "resolve",
    "resolves": "resolve",
    "resolved": "resolve",
}

_LINK = re.compile(
    r"(?<![\w-])(?P<kw>close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*"
    r"(?:"
    r"(?:https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/(?:issues|pull)/(?P<url_num>\d+))"
    r"|(?P<repo>[\w.-]+/[\w.-]+)?#(?P<num>\d+)"
    r")(?!\d)",
    re.IGNORECASE,
)


def find_references(body: str | None) -> list[tuple[str, str | None, int]]:
    if not body:
        return []
    out = []
    for m in _LINK.finditer(body):
        kw = KEYWORDS[m.group("kw").lower()]
        if m.group("url_num"):
            out.append((kw, m.group("url_repo"), int(m.group("url_num"))))
        else:
            out.append((kw, m.group("repo"), int(m.group("num"))))
    return out


def add_links(folder) -> dict:
    repo_names = {
        rid: r.get("name", "").lower()
        for rid, r in folder.records["repository"].items()
    }
    issues, prs = folder.records["issue"], folder.records["pull_request"]
    links = folder.records["link"]
    stats: Counter[str] = Counter()
    for pr in prs.values():
        refs = find_references(pr.get("body"))
        stats["prs_with_references"] += bool(refs)
        for keyword, repo, number in refs:
            if repo is not None and repo.lower() != repo_names.get(pr["repo_id"]):
                stats["cross_repo_skipped"] += 1
                continue
            target = f"{pr['repo_id']}/{number}"
            if target == pr["pr_key"]:
                stats["self_reference_skipped"] += 1
                continue
            link_key = f"{pr['pr_key']}->{number}"
            if link_key in links:
                stats["duplicate_skipped"] += 1
                continue
            target_type = (
                "issue" if target in issues else "pr" if target in prs else "unknown"
            )
            links[link_key] = {
                "link_key": link_key,
                "repo_id": pr["repo_id"],
                "pr_key": pr["pr_key"],
                "issue_key": target,
                "number": number,
                "keyword": keyword,
                "target_type": target_type,
            }
            stats[f"target_{target_type}"] += 1
    stats["links"] = len(links)
    return dict(stats)
