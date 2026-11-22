"""Work out each layout's update-replay writes from 2024 records and later events.

The 2024 records are loaded into a Folder, and each later event, in time order, is
folded in with the same code as the batch build. The documents the event could
change are built before and after with the batch build's functions, and only those
that differ are written: one line per event, with the bulk operations every layout
needs for it. Replay then times only sending them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from ingest.load.build_bulk import (
    ID_FIELD,
    NESTED_LIMIT,
    copy_link_parents,
    copy_parent,
    nested_count,
    read_records,
    s3_issue,
    s3_pr,
)
from ingest.load.mappings import LAYOUTS, entity_mappings, index_name
from ingest.transform.build_records import accepted
from ingest.transform.fold import ENTITIES, Folder, key
from ingest.transform.links import links_for
from ingest.transform.screen import Screen
from ingest.transform.validate import Validator, get

MISSING = object()
_USERS = (
    "actor",
    "payload.issue.user",
    "payload.pull_request.user",
    "payload.comment.user",
    "payload.review.user",
)
_HOUR = re.compile(r"(\d{4}-\d{2}-\d{2})-(\d{1,2})\.json\.gz$")


def hour_order(files: Iterable[Path]) -> list[Path]:
    """GH Archive hour files in time order (a plain sort puts hour 10 before 2)"""

    def k(p: Path):
        m = _HOUR.search(p.name)
        if not m:
            raise ValueError(f"not a GH Archive hour file: {p.name}")
        return m.group(1), int(m.group(2))

    return sorted(files, key=k)


def events_in_order(
    files: Iterable[Path], keep: set[int] | None, counts: Counter
) -> Iterator[dict]:
    """Accepted events, sorted by (created_at, id) within each hour, hours in order.
    An event filed in a later hour but older than the state is ignored by the
    Folder's version check, exactly as in the batch build."""
    screen, validate = Screen(), Validator()
    for path in hour_order(files):
        evs = list(accepted([path], keep, screen, validate, counts))
        evs.sort(key=lambda e: (e["created_at"], int(e["id"])))
        yield from evs
    counts["duplicates"] = validate.rejected["duplicate event id"]
    counts["rejected"] = sum(validate.rejected.values())


class State:
    """Folder plus the indexes needed to find the documents an event can change"""

    def __init__(self, records: dict[str, Iterable[dict]]):
        self.folder = Folder()
        recs = self.folder.records
        for entity in ENTITIES:
            for r in records.get(entity, ()):
                recs[entity][r[ID_FIELD[entity]]] = r
        self.comments = defaultdict(list)  # ("issue"|"pr", parent key) -> ids
        self.reviews = defaultdict(list)  # pr key -> ids
        self.links_of = defaultdict(set)  # pr key -> link keys
        self.links_to = defaultdict(set)  # target key -> link keys
        self.prs_of_repo = defaultdict(set)
        for cid, c in recs["comment"].items():
            self.comments[c["parent_type"], c["parent_key"]].append(cid)
        for rid, r in recs["review"].items():
            self.reviews[r["pr_key"]].append(rid)
        for lk, ln in recs["link"].items():
            self.links_of[ln["pr_key"]].add(lk)
            self.links_to[ln["issue_key"]].add(lk)
        for pk, pr in recs["pull_request"].items():
            self.prs_of_repo[pr["repo_id"]].add(pk)

    def repo_name(self, rid: int) -> str:
        return self.folder.records["repository"][rid].get("name", "").lower()


class View:
    """Records and child lists as they were before the event (`old` holds what the
    event changed) or as they are now"""

    def __init__(self, state: State, old: dict, old_lists: dict, before: bool):
        self.s, self.old, self.old_lists, self.before = state, old, old_lists, before

    def rec(self, entity: str, k) -> dict | None:
        if self.before and (entity, k) in self.old:
            r = self.old[entity, k]
            return None if r is MISSING else r
        return self.s.folder.records[entity].get(k)

    def ids(self, kind: str, k) -> list:
        if self.before and (kind, k) in self.old_lists:
            return self.old_lists[kind, k]
        table = {"comments": self.s.comments, "reviews": self.s.reviews}
        if kind == "links":
            return sorted(self.s.links_of.get(k, ()))
        return list(table[kind].get(k, ()))


def document(layout: str, entity: str, k, v: View) -> dict | None:
    """The document `layout` stores for one record, built as build_bulk builds it"""
    r = v.rec(entity, k)
    if r is None:
        return None
    if layout == "s2":
        if entity == "comment":
            parent = "pull_request" if r["parent_type"] == "pr" else "issue"
            return copy_parent(r, v.rec(parent, r["parent_key"]))
        if entity == "review":
            return copy_parent(r, v.rec("pull_request", r["pr_key"]))
        if entity == "link":
            return copy_link_parents(
                r, v.rec("pull_request", r["pr_key"]), v.rec("issue", r["issue_key"])
            )
    if layout == "s3":
        if entity == "issue":
            kids = [v.rec("comment", c) for c in v.ids("comments", ("issue", k))]
            return s3_issue(r, kids)
        if entity == "pull_request":
            return s3_pr(
                r,
                [v.rec("comment", c) for c in v.ids("comments", ("pr", k))],
                [v.rec("review", x) for x in v.ids("reviews", k)],
                [v.rec("link", x) for x in v.ids("links", k)],
            )
    return r


def _s3_target(entity: str, k, v: View) -> tuple[str, object]:
    """S3 has no child indexes: a child's change is a change of its parent"""
    if entity in ("issue", "pull_request", "repository", "person"):
        return entity, k
    r = v.rec(entity, k)
    if entity == "comment":
        return ("pull_request" if r["parent_type"] == "pr" else "issue"), r[
            "parent_key"
        ]
    return "pull_request", r["pr_key"]  # review or link


class Deriver:
    def __init__(self, state: State, layouts: Iterable[str], tier: str):
        self.s, self.layouts, self.tier = state, tuple(layouts), tier

    def _parent_and_child(self, ev: dict, rid: int):
        t, pl = ev["type"], ev["payload"]
        child = None
        if t == "IssuesEvent":
            parent = ("issue", key(rid, pl["issue"]["number"]))
        elif t == "IssueCommentEvent":
            is_pr = bool(pl["issue"].get("pull_request"))
            parent = (
                "pull_request" if is_pr else "issue",
                key(rid, pl["issue"]["number"]),
            )
            child = ("comment", pl["comment"]["id"])
        else:
            parent = ("pull_request", key(rid, pl["pull_request"]["number"]))
            if t == "PullRequestReviewEvent":
                child = ("review", pl["review"]["id"])
            elif t == "PullRequestReviewCommentEvent":
                child = ("comment", pl["comment"]["id"])
        return parent, child

    def apply(self, ev: dict) -> tuple[dict, dict, dict[str, list]]:
        """Fold one event. Returns the changed records, the changed child lists and,
        per layout, the candidate (entity, key) documents in write order."""
        s, recs = self.s, self.s.folder.records
        rid = ev["repo"]["id"]
        parent, child = self._parent_and_child(ev, rid)
        persons = list(
            dict.fromkeys(u for p in _USERS if (u := get(ev, f"{p}.id")) is not None)
        )
        touched = [("repository", rid), *(("person", p) for p in persons), parent]
        if child:
            touched.append(child)
        old = {
            t: dict(r) if (r := recs[t[0]].get(t[1])) is not None else MISSING
            for t in touched
        }
        pkind, pkey = parent
        ptype = "pr" if pkind == "pull_request" else "issue"
        old_lists = {
            ("comments", (ptype, pkey)): list(s.comments.get((ptype, pkey), ())),
        }
        if pkind == "pull_request":
            old_lists["reviews", pkey] = list(s.reviews.get(pkey, ()))
            old_lists["links", pkey] = sorted(s.links_of.get(pkey, ()))

        s.folder.add(ev)
        recs["repository"][rid]["events"] = old["repository", rid]["events"]

        if child and old[child] is MISSING:
            if child[0] == "comment":
                s.comments[ptype, pkey].append(child[1])
            else:
                s.reviews[pkey].append(child[1])
        new_parent = old[parent] is MISSING
        if new_parent and pkind == "pull_request":
            s.prs_of_repo[rid].add(pkey)

        relink = set()
        if pkind == "pull_request" and (
            new_parent or old[parent]["body"] != recs["pull_request"][pkey]["body"]
        ):
            relink.add(pkey)
        if old["repository", rid]["name"].lower() != s.repo_name(rid):
            relink |= s.prs_of_repo[rid]
        changed_links = []
        for pk in sorted(relink):
            changed_links += self._relink(pk, old, old_lists)
        # A link whose target first appears now changes target_type (and S2 copies)
        if new_parent:
            changed_links += self._retarget(pkey, old)

        base = list(touched) + [("link", lk) for lk in changed_links]
        plan = {}
        for layout in self.layouts:
            cands = list(base)
            if layout == "s2" and not new_parent:
                cands += self._copies(pkind, pkey, ptype)
            if layout == "s3":
                before = View(s, old, old_lists, True)
                after = View(s, old, old_lists, False)
                mapped = []
                for e, k in cands:
                    v = after if after.rec(e, k) is not None else before
                    mapped.append(_s3_target(e, k, v))
                cands = mapped
            plan[layout] = list(dict.fromkeys(cands))
        return old, old_lists, plan

    def _relink(self, pk: str, old: dict, old_lists: dict) -> list[str]:
        s, recs = self.s, self.s.folder.records
        pr = recs["pull_request"][pk]
        new = links_for(
            pr, s.repo_name(pr["repo_id"]), recs["issue"], recs["pull_request"]
        )
        keys = s.links_of.get(pk, set())
        old_lists.setdefault(("links", pk), sorted(keys))
        out = []
        for lk in sorted(keys | new.keys()):
            before = recs["link"].get(lk)
            if before == new.get(lk):
                continue
            old.setdefault(("link", lk), MISSING if before is None else dict(before))
            if lk in new:
                recs["link"][lk] = new[lk]
                s.links_to[new[lk]["issue_key"]].add(lk)
            else:
                del recs["link"][lk]
                s.links_to[before["issue_key"]].discard(lk)
            out.append(lk)
        s.links_of[pk] = set(new)
        return out

    def _retarget(self, target: str, old: dict) -> list[str]:
        recs = self.s.folder.records
        kind = "issue" if target in recs["issue"] else "pr"
        out = []
        for lk in sorted(self.s.links_to.get(target, ())):
            ln = recs["link"][lk]
            if ln["target_type"] != kind:
                old.setdefault(("link", lk), dict(ln))
                recs["link"][lk] = ln | {"target_type": kind}
                out.append(lk)
        return out

    def _copies(self, pkind: str, pkey: str, ptype: str) -> list:
        """S2 documents holding copies of this parent's fields"""
        s = self.s
        out = [("comment", c) for c in s.comments.get((ptype, pkey), ())]
        if pkind == "pull_request":
            out += [("review", r) for r in s.reviews.get(pkey, ())]
            out += [("link", lk) for lk in sorted(s.links_of.get(pkey, ()))]
        else:
            out += [("link", lk) for lk in sorted(s.links_to.get(pkey, ()))]
        return out

    def writes(self, ev: dict) -> dict[str, dict]:
        """Per layout: {"ops": [[action] or [action, source]], "docs", "bytes"}"""
        old, old_lists, plan = self.apply(ev)
        before = View(self.s, old, old_lists, True)
        after = View(self.s, old, old_lists, False)
        out = {}
        for layout, cands in plan.items():
            ops, docs, nbytes, over = [], 0, 0, 0
            for entity, k in cands:
                new = document(layout, entity, k, after)
                prev = document(layout, entity, k, before)
                meta = {"_index": index_name(layout, self.tier, entity), "_id": str(k)}
                if new is None:
                    if prev is not None:
                        ops.append([{"delete": meta}])
                        docs += 1
                    continue
                if new == prev:
                    continue
                src = json.dumps(new, ensure_ascii=False)
                ops.append([{"index": meta}, src])
                nbytes += len(src.encode())
                n = nested_count(new) if layout == "s3" else 0
                docs += 1 + n
                over += n > NESTED_LIMIT
            out[layout] = {"ops": ops, "docs": docs, "bytes": nbytes, "over": over}
        return out


def final_counts(state: State, layout: str, tier: str) -> dict[str, int]:
    entities = entity_mappings(layout)
    return {index_name(layout, tier, e): len(state.folder.records[e]) for e in entities}


def run(
    files: list[Path],
    records_dir: Path,
    out: Path,
    tier: str,
    layouts: Iterable[str] = LAYOUTS,
    keep: set[int] | None = None,
) -> dict:
    state = State({e: read_records(records_dir, e) for e in ENTITIES})
    deriver = Deriver(state, layouts, tier)
    # Only repositories in the 2024 index can be replayed.
    known = set(state.folder.records["repository"])
    keep = known if keep is None else keep & known
    counts: Counter = Counter()
    totals = {s: Counter() for s in deriver.layouts}
    by_type = {s: defaultdict(Counter) for s in deriver.layouts}
    files_out = {}
    for s in deriver.layouts:
        (out / s).mkdir(parents=True, exist_ok=True)
        files_out[s] = open(out / s / "writes.ndjson", "w")
    try:
        for ev in events_in_order(files, keep, counts):
            counts["events"] += 1
            for s, w in deriver.writes(ev).items():
                line = {"event": ev["id"], "type": ev["type"], **w}
                files_out[s].write(json.dumps(line, ensure_ascii=False) + "\n")
                n_ops = len(w["ops"])
                for c in (totals[s], by_type[s][ev["type"]]):
                    c["events"] += 1
                    c["ops"] += n_ops
                    c["docs"] += w["docs"]
                    c["bytes"] += w["bytes"]
                totals[s]["deletes"] += sum("delete" in o[0] for o in w["ops"])
                totals[s]["zero_write_events"] += n_ops == 0
                totals[s]["docs_over_nested_limit"] += w["over"]
    finally:
        for f in files_out.values():
            f.close()

    def per_event(c):
        e = c["events"] or 1
        return {
            **dict(c),
            "ops_per_event": round(c["ops"] / e, 3),
            "docs_per_event": round(c["docs"] / e, 3),
            "bytes_per_event": round(c["bytes"] / e, 1),
        }

    summary = {"tier": tier, "files": len(files), "events": dict(counts)}
    for s in deriver.layouts:
        layout_summary = {
            "layout": s,
            **per_event(totals[s]),
            "by_type": {t: per_event(c) for t, c in sorted(by_type[s].items())},
            "expected_counts": final_counts(state, s, tier),
        }
        (out / s / "summary.json").write_text(json.dumps(layout_summary, indent=2))
        summary[s] = layout_summary
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder", type=Path, help="GH Archive hour files to replay")
    p.add_argument("--records", type=Path, default=Path("data/records"))
    p.add_argument("--out", type=Path, default=Path("data/replay"))
    p.add_argument("--tier", default="dev")
    p.add_argument("--layout", choices=LAYOUTS + ("all",), default="all")
    p.add_argument("--repos", type=Path, help="the tier's repository id file")
    args = p.parse_args(argv)

    files = list(args.folder.glob("*.json.gz"))
    if not files:
        print(f"No *.json.gz files in {args.folder}", file=sys.stderr)
        return 1
    keep = {int(x) for x in args.repos.read_text().split()} if args.repos else None
    layouts = LAYOUTS if args.layout == "all" else (args.layout,)
    summary = run(files, args.records, args.out, args.tier, layouts, keep)
    text = json.dumps(summary, indent=2)
    (args.out / "summary.json").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
