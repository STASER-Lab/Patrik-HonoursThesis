"""Bulk documents must fit their mappings and have the shape of their strategy."""

import json

import pytest

from ingest.load.bulk import documents, write_bulk
from ingest.load.mappings import S2_COPIED, entity_mappings

from .test_mappings import sample_records


@pytest.fixture
def records_dir(tmp_path):
    f = sample_records()
    for entity in f.records:
        with open(tmp_path / f"{entity}.ndjson", "w") as out:
            for r in f.iter_records(entity):
                out.write(json.dumps(r) + "\n")
    return tmp_path


def fits(doc: dict, properties: dict, path=""):
    for k, v in doc.items():
        assert k in properties, f"unmapped field {path}{k}"
        if properties[k].get("type") == "nested":
            for child in v:
                fits(child, properties[k]["properties"], f"{path}{k}.")


@pytest.mark.parametrize("strategy", ["s1", "s2", "s3", "s4"])
def test_every_document_fits_its_strict_mapping(records_dir, strategy):
    mappings = entity_mappings(strategy)
    seen = set()
    # Ignore doc_id since this test only validates document fields.
    for entity, _, doc in documents(strategy, records_dir):
        fits(doc, mappings[entity]["properties"])
        seen.add(entity)
    assert seen == set(mappings)


def test_s2_comment_carries_its_prs_fields(records_dir):
    docs = {(e, i): d for e, i, d in documents("s2", records_dir)}
    c = docs[("comment", "77")]
    pr = docs[("pull_request", "10/5")]
    for f in S2_COPIED:
        assert c[f"parent_{f}"] == pr[f]
    assert c["parent_merged"] is True


def test_s3_pr_holds_its_comments_and_reviews(records_dir):
    docs = {(e, i): d for e, i, d in documents("s3", records_dir)}
    pr = docs[("pull_request", "10/5")]
    assert [c["comment_id"] for c in pr["comments"]] == [77]
    assert [r["review_id"] for r in pr["reviews"]] == [55]
    assert [c["comment_id"] for c in docs[("issue", "10/6")]["comments"]] == [79]
    assert not any(e in ("comment", "review") for e, _ in docs)


def test_bulk_file_format_and_ids(records_dir, tmp_path):
    s = write_bulk("s1", records_dir, tmp_path / "bulk")
    lines = (tmp_path / "bulk" / "s1" / "pull_request.ndjson").read_text().splitlines()
    assert json.loads(lines[0]) == {"index": {"_id": "10/5"}}
    assert json.loads(lines[1])["pr_key"] == "10/5"
    assert s["entities"]["pull_request"]["docs"] == 2


# Batch test TBC


def test_s2_link_carries_both_parents(records_dir):
    docs = {(e, i): d for e, i, d in documents("s2", records_dir)}
    ln = docs[("link", "10/9->6")]
    assert ln["pr_merged"] is False and ln["pr_author_id"] == 1
    assert ln["issue_created_at"] == "2024-01-10T10:00:00Z"
    assert "issue_merged" not in ln


def test_s3_pr_holds_its_links(records_dir):
    docs = {(e, i): d for e, i, d in documents("s3", records_dir)}
    assert [
        link["issue_key"] for link in docs[("pull_request", "10/9")]["links"]
    ] == ["10/6"]
    assert docs[("pull_request", "10/5")]["links"] == []
