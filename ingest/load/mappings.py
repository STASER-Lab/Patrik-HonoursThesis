"""Index settings and mappings for strategies"""

from __future__ import annotations

import copy

STRATEGIES = ("s1", "s2", "s3", "s4")

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

ENTITY_FIELDS: dict[str, list[str]] = {
    "repository": ["repo_id", "name", "is_fork"],
    "person": ["person_id", "login", "is_bot"],
    "issue": [
        "issue_key",
        "repo_id",
        "number",
        "author_id",
        "author_is_bot",
        "title",
        "body",
        "state",
        "created_at",
        "closed_at",
    ],
    "pull_request": [
        "pr_key",
        "repo_id",
        "number",
        "author_id",
        "author_is_bot",
        "title",
        "body",
        "state",
        "created_at",
        "closed_at",
        "merged_at",
        "merged",
    ],
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

S2_COPIED = [
    "author_id",
    "author_is_bot",
    "state",
    "created_at",
    "closed_at",
    "merged",
    "merged_at",
]

S2_LINK_COPIED = {
    "pr": S2_COPIED,
    "issue": ["author_id", "author_is_bot", "state", "created_at", "closed_at"],
}

LOOKUP_INDEXES = ("pull_request", "issue", "person", "link")


def _properties(fields: list[str]) -> dict:
    return {f: copy.deepcopy(FIELD_TYPES[f]) for f in fields}


def s2_link_copy_properties() -> dict:
    return {
        f"{parent}_{f}": copy.deepcopy(FIELD_TYPES[f])
        for parent, fields in S2_LINK_COPIED.items()
        for f in fields
    }


def _mapping(properties: dict) -> dict:
    return {"dynamic": "strict", "properties": properties}


def s2_copy_properties() -> dict:
    return {f"parent_{f}": copy.deepcopy(FIELD_TYPES[f]) for f in S2_COPIED}


def entity_mappings(strategy: str) -> dict[str, dict]:
    """
    Strategies:
        s1: one index per entity; children hold their parent's key
        s2: parent fields copied onto children, stored as parent_<field>
        s3: children live inside their parents
        s4: indexes created in lookup mode
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    if strategy in ("s1", "s4"):
        return {e: _mapping(_properties(f)) for e, f in ENTITY_FIELDS.items()}
    if strategy == "s2":
        out = {e: _mapping(_properties(f)) for e, f in ENTITY_FIELDS.items()}
        for child in ("comment", "review"):
            out[child]["properties"].update(s2_copy_properties())
        out["link"]["properties"].update(s2_link_copy_properties())
        return out
    if strategy == "s3":
        comments = {
            "type": "nested",
            "properties": _properties(ENTITY_FIELDS["comment"]),
        }
        reviews = {"type": "nested", "properties": _properties(ENTITY_FIELDS["review"])}
        links = {"type": "nested", "properties": _properties(ENTITY_FIELDS["link"])}
        pr = _properties(ENTITY_FIELDS["pull_request"]) | {
            "comments": comments,
            "reviews": reviews,
            "links": links,
        }
        issue = _properties(ENTITY_FIELDS["issue"]) | {
            "comments": copy.deepcopy(comments)
        }  # deepcopy to avoid sharing the same object between issue and pr
        return {
            "repository": _mapping(_properties(ENTITY_FIELDS["repository"])),
            "person": _mapping(_properties(ENTITY_FIELDS["person"])),
            "issue": _mapping(issue),
            "pull_request": _mapping(pr),
        }


def index_name(strategy: str, tier: str, entity: str) -> str:
    return f"{strategy}-{tier}-{entity}"


def index_definitions(
    strategy: str, tier: str, shards: int = 1, replicas: int = 0
) -> dict[str, dict]:
    out = {}
    for entity, mapping in entity_mappings(strategy).items():
        if strategy == "s4" and entity in LOOKUP_INDEXES:
            settings = {"index": {"mode": "lookup", "number_of_replicas": replicas}}
        else:
            settings = {
                "index": {"number_of_shards": shards, "number_of_replicas": replicas}
            }
        out[index_name(strategy, tier, entity)] = {
            "settings": settings,
            "mappings": mapping,
        }
    return out
