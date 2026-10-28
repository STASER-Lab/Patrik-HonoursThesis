"""Mappings must match the records exactly, so strict indexes accept every record."""

import pytest

from ingest.load.mappings import (
    ENTITY_FIELDS,
    FIELD_TYPES,
    LOOKUP_INDEXES,
    S2_COPIED,
    entity_mappings,
    index_definitions,
)
from ingest.transform.fold import Folder
from ingest.transform.links import add_links

from .test_operations import BOB, comment_on_pr, ev, pr_merged, pr_obj, pr_opened


def sample_records():
    issue_comment = comment_on_pr(eid=7, cid=79)
    del issue_comment["payload"]["issue"]["pull_request"]
    issue_comment["payload"]["issue"]["number"] = 6
    review = ev(
        4,
        "PullRequestReviewEvent",
        "2024-01-10T11:30:00Z",
        {
            "action": "created",
            "pull_request": pr_obj(),
            "review": {
                "id": 55,
                "user": BOB,
                "state": "APPROVED",
                "body": "",
                "submitted_at": "2024-01-10T11:30:00Z",
            },
        },
        actor=BOB,
    )
    linking_pr = ev(
        8,
        "PullRequestEvent",
        "2024-01-10T13:00:00Z",
        {
            "action": "opened",
            "number": 9,
            "pull_request": {**pr_obj(number=9), "body": "Fixes #6"},
        },
    )
    f = Folder()
    for e in (
        pr_opened(),
        comment_on_pr(),
        pr_merged(),
        issue_comment,
        review,
        linking_pr,
    ):
        f.add(e)
    add_links(f)
    return f


def test_every_record_field_is_mapped_and_nothing_extra():
    f = sample_records()
    for entity, fields in ENTITY_FIELDS.items():
        recs = list(f.iter_records(entity))
        assert recs, f"no sample {entity}"
        for rec in recs:
            assert set(rec) == set(fields), (entity, set(rec) ^ set(fields))


def test_all_fields_have_a_type():
    for fields in ENTITY_FIELDS.values():
        assert set(fields) <= set(FIELD_TYPES)


@pytest.mark.parametrize("strategy", ["s1", "s2", "s3", "s4"])
def test_mappings_are_strict(strategy):
    for m in entity_mappings(strategy).values():
        assert m["dynamic"] == "strict"


def test_s2_children_carry_parent_copies_only_on_children():
    m = entity_mappings("s2")
    for child in ("comment", "review"):
        assert {f"parent_{x}" for x in S2_COPIED} <= set(m[child]["properties"])
    assert not any(
        k.startswith("parent_") and k != "parent_key" and k != "parent_type"
        for k in m["pull_request"]["properties"]
    )
    assert "parent_body" not in m["comment"]["properties"]  # text is never copied


def test_s3_nests_children_and_has_no_child_indexes():
    m = entity_mappings("s3")
    assert set(m) == {"repository", "person", "issue", "pull_request"}
    assert m["pull_request"]["properties"]["comments"]["type"] == "nested"
    assert m["pull_request"]["properties"]["reviews"]["type"] == "nested"
    assert m["issue"]["properties"]["comments"]["type"] == "nested"
    assert m["pull_request"]["properties"]["links"]["type"] == "nested"


def test_s4_parents_are_lookup_indexes_and_children_are_not():
    d = index_definitions("s4", "dev", shards=3)
    for entity in LOOKUP_INDEXES:
        s = d[f"s4-dev-{entity}"]["settings"]["index"]
        assert s["mode"] == "lookup" and "number_of_shards" not in s
    assert d["s4-dev-comment"]["settings"]["index"]["number_of_shards"] == 3


def test_same_field_has_same_type_in_every_strategy():
    for s in ("s1", "s2", "s3", "s4"):
        for m in entity_mappings(s).values():
            for name, spec in m["properties"].items():
                if name in FIELD_TYPES:
                    assert spec == FIELD_TYPES[name], (s, name)
