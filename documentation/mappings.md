# Index layouts for S1 to S4

All four strategies are built from the same records (`documentation/record-model.md`). They differ only
in document shape. Index names: `<strategy>-<tier>-<entity>`, e.g. `s1-10gb-pull_request`.

## Field types

| Kind | Fields | Elasticsearch type | Why |
| --- | --- | --- | --- |
| Keys | `pr_key`, `issue_key`, `parent_key`, `link_key`, `keyword`, `target_type` | `keyword` | Exact match, terms aggregations, LOOKUP JOIN |
| Numeric ids | `repo_id`, `person_id`, `author_id`, `comment_id`, `review_id`, `number` | `long` | Compact |
| Categories | `state`, `kind`, `parent_type`, `login`, `name` | `keyword` | Filters and aggregations |
| Flags | `merged`, `is_bot`, `is_fork`, `author_is_bot` | `boolean` | |
| Times | `created_at`, `closed_at`, `merged_at`, `submitted_at` | `date` | Date histograms |
| Text | `title`, `body` | `text` (standard analyzer), no `keyword` sub-field | No sub-field, to keep storage honest |

Mappings are strict (`"dynamic": "strict"`): a field not in the mapping is an error, not silently added.

## S1: separate indexes, joined in code

Six indexes, one per entity, each document = one record. Children hold their parent's key
(`comment.parent_key`, `review.pr_key`).

## S2: flat copies

S1's indexes, but each child also carries copies of its parent's fields, prefixed `parent_`:
comments and reviews of a PR get `parent_author_id`, `parent_created_at`, `parent_state`,
`parent_merged`, `parent_merged_at`, `parent_closed_at`.

## S3: nested documents

One document per PR holding `comments[]` and `reviews[]` as `nested` arrays. Issues likewise hold
their `comments[]`. Repository and person stay separate indexes. One change to a comment rewrites
the whole PR document. Elasticsearch limits nested objects per document (`index.mapping.nested_objects.limit`,
default 10,000).

## S4: ES|QL LOOKUP JOIN

S1's indexes, with the parent indexes (`pull_request`, `issue`, `person`) created in
`index.mode: lookup`.

## Links

- S1: a `link` index (`link_key`, `pr_key`, `issue_key`, `target_type`, ...). Joined in Python.
- S2: links copy both parents: `pr_author_id`, `pr_author_is_bot`, `pr_state`, `pr_created_at`, `pr_closed_at`,
`pr_merged`, `pr_merged_at` and `issue_author_id`, `issue_author_is_bot`, `issue_state`, `issue_created_at`, `issue_closed_at`.
A PR merge and an issue close both rewrite links (write amplification in both directions).
- S3: links are nested in their PR (`links[]`), since the PR's body creates them. The issue side needs a
reverse lookup: nesting has to pick one side of a many-to-many. Links count toward the nested-object limit.
- S4: the link index is a lookup index too, so queries can join from the issue side:
`FROM issues | LOOKUP JOIN links ON issue_key | LOOKUP JOIN pull_requests ON pr_key`.
