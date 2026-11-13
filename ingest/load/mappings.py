"""Index settings and strict mappings for the four layouts.

S1  one index per entity. Joins happen in the client.
S2  as S1, but children carry copies of their parent's fields (`parent_*`. Links
    carry `pr_*` and `issue_*`), so filters on the parent need no join.
S3  comments, reviews and links are nested in their issue or PR. There are no child
    indexes.
S4  as S1, with parents as lookup indexes for ES|QL LOOKUP JOIN.

Mappings are strict, so an unmapped field fails the load instead of being indexed
dynamically.
"""

from __future__ import annotations

LAYOUTS = ("s1", "s2", "s3", "s4")

# One type per field name in every layout, so layouts are compared like for like
FIELD_TYPES: dict[str, dict] = {
    "pr_key": {"type": "keyword"},
    "issue_key": {"type": "keyword"},
    "parent_key": {"type": "keyword"},
    "link_key": {"type": "keyword"},
    "keyword": {"type": "keyword"},
    "target_type": {"type": "keyword"},
    "repo_id": {"type": "long"},
    "person_id": {"type": "long"},
    "author_id": {"type": "long"},
    "comment_id": {"type": "long"},
    "review_id": {"type": "long"},
    "number": {"type": "long"},
    "events": {"type": "long"},
    "state": {"type": "keyword"},
    "kind": {"type": "keyword"},
    "parent_type": {"type": "keyword"},
    "login": {"type": "keyword"},
    "name": {"type": "keyword"},
    "merged": {"type": "boolean"},
    "is_bot": {"type": "boolean"},
    "is_fork": {"type": "boolean"},
    "author_is_bot": {"type": "boolean"},
    "created_at": {"type": "date"},
    "closed_at": {"type": "date"},
    "merged_at": {"type": "date"},
    "submitted_at": {"type": "date"},
    "title": {"type": "text"},
    "body": {"type": "text"},
}

_THREAD = [
    "repo_id",
    "number",
    "author_id",
    "author_is_bot",
    "title",
    "body",
    "state",
    "created_at",
    "closed_at",
]

ENTITY_FIELDS: dict[str, list[str]] = {
    "repository": ["repo_id", "name", "is_fork", "events"],
    "person": ["person_id", "login", "is_bot"],
    "issue": ["issue_key", *_THREAD],
    "pull_request": ["pr_key", *_THREAD, "merged_at", "merged"],
    "comment": [
        "comment_id",
        "repo_id",
        "kind",
        "parent_type",
        "parent_key",
        "author_id",
        "author_is_bot",
        "body",
        "created_at",
    ],
    "review": [
        "review_id",
        "repo_id",
        "pr_key",
        "author_id",
        "author_is_bot",
        "state",
        "body",
        "submitted_at",
    ],
    "link": [
        "link_key",
        "repo_id",
        "pr_key",
        "issue_key",
        "number",
        "keyword",
        "target_type",
    ],
}

# Only fields that filters and joins need. Text is never copied
_ISSUE_COPIED = ["author_id", "author_is_bot", "state", "created_at", "closed_at"]
S2_COPIED = [*_ISSUE_COPIED, "merged", "merged_at"]
S2_LINK_COPIED = {"pr": S2_COPIED, "issue": _ISSUE_COPIED}

LOOKUP_INDEXES = ("pull_request", "issue", "person", "link")


def _properties(fields: list[str]) -> dict:
    return {f: dict(FIELD_TYPES[f]) for f in fields}


def entity_mappings(layout: str) -> dict[str, dict]:
    if layout not in LAYOUTS:
        raise ValueError(f"unknown layout {layout!r}")
    props = {e: _properties(f) for e, f in ENTITY_FIELDS.items()}
    if layout == "s2":
        parent = {f"parent_{k}": v for k, v in _properties(S2_COPIED).items()}
        for child in ("comment", "review"):
            props[child] |= parent
        props["link"] |= {
            f"{p}_{k}": v
            for p, fields in S2_LINK_COPIED.items()
            for k, v in _properties(fields).items()
        }
    elif layout == "s3":
        nested = {
            f"{e}s": {"type": "nested", "properties": props.pop(e)}
            for e in ("comment", "review", "link")
        }
        props["issue"]["comments"] = {
            "type": "nested",
            "properties": _properties(ENTITY_FIELDS["comment"]),
        }
        props["pull_request"] |= nested
    return {e: {"dynamic": "strict", "properties": p} for e, p in props.items()}


def index_name(layout: str, tier: str, entity: str) -> str:
    return f"{layout}-{tier}-{entity}"


def index_definitions(
    layout: str, tier: str, shards: int = 1, replicas: int = 0
) -> dict[str, dict]:
    out = {}
    for entity, mapping in entity_mappings(layout).items():
        # Lookup mode fixes a single shard, so `shards` does not apply
        mode = (
            {"mode": "lookup"}
            if layout == "s4" and entity in LOOKUP_INDEXES
            else {"number_of_shards": shards}
        )
        out[index_name(layout, tier, entity)] = {
            "settings": {"index": mode | {"number_of_replicas": replicas}},
            "mappings": mapping,
        }
    return out
