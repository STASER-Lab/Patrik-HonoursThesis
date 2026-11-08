# Decision Records

## D-001 k8s instead of Docker

**Status** - Closed

**Proposed** - Ship Elasticsearch with k3s and Elastic Cloud on Kubernetes (ECK)

**Context** - The original plan was to use Docker Compose

**Decision** - Use k3s and ECK beceause one control VM can manage every node

**Consequences** - Easier configuration

## D-002 Pin Elasticsearch 9.5.4

**Status** - *Active*. Need to pin the version in the ECK YAML

**Proposed** - Use the same Elasticsearch version across the research project

**Context** - Want local and Arbutus development results to agree. Currently 9.5.4 (arm64) is installed

**Decision** - Use Elasticsearch version 9.5.4

**Consequences** - Consistent results across local and Arbutus. Also, helps reproducibility

## D-003 Use BigQuery Sandbox for ranking and volume estimates

**Status** - Closed

**Proposed** - Use BigQuery or try to gather estimates locally or even not at all

**Context** - Estimates are useful for planning and determining how many repositories fit in a data tier, etc

**Decision** - Went with BigQuery sandbox because it gives 1 TB of FREE queries

**Consequences** - Gained a high level overview into GH Archive's 2024 data set (7.7 million repositories) and saved resulting tables from queries. Due to the extreme skew of the repository data, I will populate tiers based on how many events repositories have not how many repositories exist at a certain event count. For example, at 10 GB there might be 10 repositoires with 5 event counts, 30 with 100, 1 with 300, and 0 with 1000 plus

## D-004 Filter low quality repositories based on BigQuery experiment

**Status** - Closed

**Proposed** - Filter data from GH Archive 2024 dataset to reduce near empty and bot repositories

**Context** - GitHub data is skewed and bad data impacts measurements

**Decision** - Keep a repository if it has >= 3 distinct actors, no single account produces > 80% of its events**, and <= 1,000 events per actor. Forks should also be filtered. This avoids using a third party tool like GitHub Search to filter the data since we would have our own

**Consequences** - 1,078,278 of 7,724,086 repositories kept (14%), with 181.7M of 283.9M events (64%). Median 26 events per repository, p99 2,188. The 1 TB tier (~67.5M events) needs about 37% of the filtered pool. A small amount of repositories are missed (i.e. bot heavy projects that are just above the event/actor line of 1000). Forks cannot be seen in BigQuery without scanning the payload column (~4.2 TB, over the sandbox limit), so the ETL drops them instead (`is_fork`, from PR events) and reports the events removed (`forks_dropped`). Tiers therefore end slightly under their event targets

## D-005 Record model

**Status** - Closed

**Proposed** - Define a structure for records

**Context** - Use number-based keys for issues and PRs, snapshots from any event that touches the parent (latest event wins), all titles and bodies kept, pre-2024 entities kept with their real `created_at`.

**Decision** - To use the above ruleset

**Consequences** - Realistic storage costs for the experiment, no orphaned comments on PRs opened before 2024, comments refrence PRs by number only and issues can link to PRs in the same repository when a closing keyword is identified

--

## D-006 Mapping choices for S1 to S4

**Status** - Closed

**Proposed** - Use a curated bot list for observation, children copy non-test fields only and S4 has its own index set, with `pull_request`, `issue`, `person` and `link` in `index.mode: lookup`

**Context** - Define these choice before mappings are coded in

**Decision** - Go ahead with the proposed decisions

**Consequences** - Reduce text dupilication, easier to load and drop strategies and information on bot activity. Update: `link` added as a lookup index, since `LOOKUP JOIN` can only join into lookup indexes and issue-to-PR queries need it

--

## D-007 Fold by repository buckets

**Status** - Closed

**Proposed** - Before folding, partition validated events into N buckets by `hash(repo_id)` on disk, then fold each bucket independently. People are merged across buckets at the end

**Context** - Reduce peak memory usage when operating on large data tiers

**Decision** - Go with the buckets approach for now

**Consequences** - Every issue, PR, comment and review belongs to exactly one repository, so buckets never need each other, and memory is bounded by bucket size.

--

## D-008 Storage measured after force-merge to one segment

**Status** - Closed

**Proposed** - Measure index size after force merge for storage only

**Context** - When indexing ES has segments merging in the background

**Decision** - Go with the proposed plan and also measure as-loaded size size alongside it

**Consequences** - Deterministic size on each run. Not relying on timing

--

## D-009 Bot detection by name rule and reviewed lists

**Status** - Closed

**Proposed** - Add a login-suffix rule ("bot", including "robot"), an exception list for people whose login ends in "bot", and a small curated list of accounts that name themselves as automation or post templated output. The lists are fixed for the whole study

**Context** - GitHub only marks GitHub Apps. User-type bots passed as humans

**Decision** - Go with the proposed rule, in `ingest/transform/bots.py`

**Consequences** - The lists are not re-reviewed per tier, so every tier uses the same rule. Each tier's share of bot-authored records is reported from the ETL summary (`authored_records.bot_share`). Bots posting through a person's own account (status pages, mirrors) are still missed and are reported as a threat to validity

--

## D-010 ES|QL row limit is a capability result

**Status** - Closed

**Proposed** - Keep the default ES|QL row limit (10,000) and record S4 answers that reach it as `limit` (Not supported) instead of raising the cluster setting or paging

**Context** - S4's Q1, Q3 and Q5 return one row per PR or issue, so they can reach the limit on the largest repositories. Raising `esql.query.result_truncation_max_size` is a non-default configuration, and paging makes S4 a workaround

**Decision** - Go with the proposed plan

**Consequences** - `check.py` reports pass, fail and limit separately, and only failures fail the run. The limit is reported as an RQ1 finding

--

## D-011 Fixed benchmark repositories per tier

**Status** - Closed

**Proposed** - Pick small, median and largest from repositories where every query has data, ranked by accepted events (the measure tiers are built on), and save the picks per tier

**Context** - Picking by PR comment count from the sample chose repositories with about one PR, so Q4 to Q6 had nothing to answer

**Decision** - Go with the proposed plan (`benchmark/repos/<tier>.json`, re-pick with `--repick`)

**Consequences** - Every query's strategies are exercised on every pick, and runs are repeatable. The small pick is the smallest repository with data for every query, not the smallest overall

--

## D-012 Tier construction

**Status** - Closed

**Proposed** - Build the three tiers from the D-004 pool (`ingest/sql/tier_pool_2024.sql`) with `ingest/extract/tiers.py`: powers-of-ten size bands filled in 2024's event proportions, a fixed random order (seed 2024), a 10% cap per repository and nesting

**Context** - test.md fixes the four steps but not the band edges, the order within a band, or how nesting and the cap interact

**Decision** - Each tier starts from the smaller one, then fills every band until it reaches its share, so the last repository in a band may overshoot. A stricter rule (only add a repository that brings the band closer to its share) was tried and rejected: it never admits the largest repositories, because a giant always overshoots its small band

**Consequences** - On a synthetic pool shaped like D-004 (1.08M repositories, median 26 events), tiers land 1-3% over their event targets with median 24-25 events, top-1% share 0.32-0.35 (pool 0.34), and a 747k-event repository in the 1 TB tier. The lists (`ingest/tiers/`) are committed so the replication package needs no BigQuery access

--

## D-XXX

**Status** - TBC

**Proposed** - TBC

**Context** - TBC

**Decision** - TBC

**Consequences** - TBC

--

Format adapted from Michael Nygard's ADR Markdown [template](https://www.adr.zone/adr-template/nygard)
