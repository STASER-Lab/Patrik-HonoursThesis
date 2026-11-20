import json
from types import SimpleNamespace

import pytest

from ingest.load import index_bulk
from ingest.load.build_bulk import documents, write_bulk
from ingest.load.index_bulk import batches
from ingest.load.mappings import (
    ENTITY_FIELDS,
    FIELD_TYPES,
    LAYOUTS,
    LOOKUP_INDEXES,
    S2_COPIED,
    entity_mappings,
    index_definitions,
)
from ingest.transform.fold import Folder
from ingest.transform.links import add_links

from .test_transform import BOB, comment_on_pr, ev, pr_merged, pr_obj, pr_opened


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
        recs = list(f.records[entity].values())
        assert recs, f"no sample {entity}"
        for rec in recs:
            assert set(rec) == set(fields), (entity, set(rec) ^ set(fields))


def test_s2_children_carry_parent_copies_only_on_children():
    m = entity_mappings("s2")
    for child in ("comment", "review"):
        assert {f"parent_{x}" for x in S2_COPIED} <= set(m[child]["properties"])
    assert not any(k.startswith("parent_") for k in m["pull_request"]["properties"])
    assert "parent_body" not in m["comment"]["properties"]


def test_s3_nests_children_and_has_no_child_indexes():
    m = entity_mappings("s3")
    assert set(m) == {"repository", "person", "issue", "pull_request"}
    for entity, child in (
        ("pull_request", "comments"),
        ("pull_request", "reviews"),
        ("pull_request", "links"),
        ("issue", "comments"),
    ):
        assert m[entity]["properties"][child]["type"] == "nested"


def test_s4_parents_are_lookup_indexes_and_children_are_not():
    d = index_definitions("s4", "dev", shards=3)
    for entity in LOOKUP_INDEXES:
        s = d[f"s4-dev-{entity}"]["settings"]["index"]
        assert s["mode"] == "lookup" and "number_of_shards" not in s
    assert d["s4-dev-comment"]["settings"]["index"]["number_of_shards"] == 3


def test_same_field_has_same_type_in_every_layout():
    for s in LAYOUTS:
        for m in entity_mappings(s).values():
            for name, spec in m["properties"].items():
                if name in FIELD_TYPES:
                    assert spec == FIELD_TYPES[name], (s, name)


@pytest.fixture
def records_dir(tmp_path):
    for entity, table in sample_records().records.items():
        (tmp_path / f"{entity}.ndjson").write_text(
            "".join(json.dumps(r) + "\n" for r in table.values())
        )
    return tmp_path


def fits(doc: dict, properties: dict, path=""):
    for k, v in doc.items():
        assert k in properties, f"unmapped field {path}{k}"
        if properties[k].get("type") == "nested":
            for child in v:
                fits(child, properties[k]["properties"], f"{path}{k}.")


@pytest.mark.parametrize("layout", LAYOUTS)
def test_every_document_fits_its_strict_mapping(records_dir, layout):
    mappings = entity_mappings(layout)
    seen = set()
    for entity, _, doc in documents(layout, records_dir):
        fits(doc, mappings[entity]["properties"])
        seen.add(entity)
    assert seen == set(mappings)


def test_s2_children_and_links_carry_parent_fields(records_dir):
    docs = {(e, i): d for e, i, d in documents("s2", records_dir)}
    c, pr, ln = (
        docs["comment", "77"],
        docs["pull_request", "10/5"],
        docs["link", "10/9->6"],
    )
    assert all(c[f"parent_{f}"] == pr[f] for f in S2_COPIED)
    assert c["parent_merged"] is True
    assert ln["pr_merged"] is False and ln["pr_author_id"] == 1
    assert ln["issue_created_at"] == "2024-01-10T10:00:00Z"
    assert "issue_merged" not in ln


def test_s3_embeds_comments_reviews_and_links(records_dir):
    docs = {(e, i): d for e, i, d in documents("s3", records_dir)}
    pr = docs["pull_request", "10/5"]
    assert [c["comment_id"] for c in pr["comments"]] == [77]
    assert [r["review_id"] for r in pr["reviews"]] == [55]
    assert [c["comment_id"] for c in docs["issue", "10/6"]["comments"]] == [79]
    assert [ln["issue_key"] for ln in docs["pull_request", "10/9"]["links"]] == ["10/6"]
    assert pr["links"] == []
    assert not any(e in ("comment", "review", "link") for e, _ in docs)


def test_bulk_file_format_and_ids(records_dir, tmp_path):
    s = write_bulk("s1", records_dir, tmp_path / "bulk")
    lines = (tmp_path / "bulk" / "s1" / "pull_request.ndjson").read_text().splitlines()
    assert json.loads(lines[0]) == {"index": {"_id": "10/5"}}
    assert json.loads(lines[1])["pr_key"] == "10/5"
    assert s["entities"]["pull_request"]["docs"] == 2


REPOS = (10, 11, 12, 13, 14, 15, 16)
KEYS = ("issue_key", "pr_key", "parent_key", "link_key")


@pytest.fixture
def many_repos_dir(tmp_path):
    """The sample family copied into several repositories, plus a comment tie."""
    out = tmp_path / "records"
    out.mkdir()
    for entity, table in sample_records().records.items():
        rows = []
        for repo in REPOS:
            for r in table.values():
                r = dict(r)
                if "repo_id" in r and entity != "repository":
                    r["repo_id"] = repo
                    for k in KEYS:
                        if k in r:
                            r[k] = r[k].replace("10/", f"{repo}/")
                    for k in ("comment_id", "review_id"):
                        if k in r:
                            r[k] += repo * 1000
                rows.append(r)
                if entity == "comment" and r["parent_type"] == "pr":
                    rows.append(r | {"comment_id": r["comment_id"] + 500})
            if entity in ("repository", "person"):
                break
        (out / f"{entity}.ndjson").write_text(
            "".join(json.dumps(r) + "\n" for r in rows)
        )
    return out


@pytest.mark.parametrize("layout", ("s2", "s3"))
@pytest.mark.parametrize("buckets", (2, 3, 7, 50))
def test_buckets_give_the_same_documents(many_repos_dir, tmp_path, layout, buckets):
    one = list(documents(layout, many_repos_dir))
    split = list(documents(layout, many_repos_dir, buckets, tmp_path / "work"))
    assert len(split) == len(one)
    assert dict(((e, i), d) for e, i, d in split) == dict(
        ((e, i), d) for e, i, d in one
    )
    assert not (tmp_path / "work").exists()


def test_bucketed_s3_keeps_tied_children_in_input_order(many_repos_dir, tmp_path):
    docs = {(e, i): d for e, i, d in documents("s3", many_repos_dir, 3, tmp_path / "w")}
    ids = [c["comment_id"] for c in docs["pull_request", "12/5"]["comments"]]
    assert ids == [12077, 12577]


def test_write_bulk_with_buckets_matches_and_cleans_up(many_repos_dir, tmp_path):
    for layout in ("s2", "s3"):
        a = write_bulk(layout, many_repos_dir, tmp_path / "one")
        b = write_bulk(layout, many_repos_dir, tmp_path / "many", buckets=4)
        assert a == b
        assert not (tmp_path / "many" / layout / "_buckets").exists()


def test_buckets_need_a_work_directory(many_repos_dir):
    with pytest.raises(ValueError):
        list(documents("s3", many_repos_dir, 2))
    with pytest.raises(ValueError):
        list(documents("s3", many_repos_dir, 0))


def test_load_batches_split_by_document_count(tmp_path):
    p = tmp_path / "x.ndjson"
    p.write_text(
        "".join(f'{{"index":{{"_id":"{i}"}}}}\n{{"n":{i}}}\n' for i in range(5))
    )
    assert [len(ops) // 2 for ops, _ in batches(p, 2)] == [2, 2, 1]


class FakeLoadES:
    def __init__(self):
        self.calls = []
        rec = lambda name: lambda **kw: self.calls.append((name, kw))  # noqa: E731
        self.indices = SimpleNamespace(
            exists=lambda index: False,
            create=rec("create"),
            refresh=rec("refresh"),
            put_settings=rec("put_settings"),
        )

    def bulk(self, index, operations, filter_path):
        self.calls.append(("bulk", {"index": index}))
        return {"errors": False}

    def count(self, index):
        return {"count": 2}


def _bulk_dir(tmp_path):
    out = tmp_path / "bulk" / "s1"
    out.mkdir(parents=True)
    for entity in ENTITY_FIELDS:  # every S1 index needs a bulk file
        (out / f"{entity}.ndjson").write_text(
            "".join(f'{{"index":{{"_id":"{i}"}}}}\n{{"n":{i}}}\n' for i in range(2))
        )
    return tmp_path / "bulk"


def _run_load(tmp_path, monkeypatch, es):
    monkeypatch.setattr(index_bulk, "client", lambda env_file: es)
    saved = {}
    monkeypatch.setattr(
        index_bulk, "save_result", lambda name, es, data: saved.update(data) or "x"
    )
    argv = ["--layout", "s1", "--bulk-dir", str(_bulk_dir(tmp_path)), "--recreate"]
    return index_bulk.main(argv), saved


def test_load_runs_with_refresh_off_and_times_one_refresh_per_index(
    tmp_path, monkeypatch
):
    es = FakeLoadES()
    code, saved = _run_load(tmp_path, monkeypatch, es)
    assert code == 0
    created = [kw for name, kw in es.calls if name == "create"]
    assert all(c["settings"]["index"]["refresh_interval"] == "-1" for c in created)
    assert all(c["settings"]["index"]["number_of_replicas"] == 0 for c in created)
    order = [(n, kw["index"]) for n, kw in es.calls if n in ("bulk", "refresh")]
    names = sorted(f"s1-dev-{e}" for e in ENTITY_FIELDS)
    assert order == [(step, n) for n in names for step in ("bulk", "refresh")]
    assert es.calls[-1][0] == "put_settings"
    assert es.calls[-1][1]["settings"] == {"index": {"refresh_interval": None}}
    r = saved["indexes"][0]
    assert 0 <= r["refresh_seconds"] <= r["seconds"]
