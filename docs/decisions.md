# Decision Records

## D-001 k8s instead of Docker

**Status** - Closed

**Proposed** - Ship Elasticsearch with k3s and Elastic Cloud on Kubernetes (ECK)

**Context** - The original plan was to use Docker Compose

**Decision** - Use k3s and ECK beceause one control VM can manage every node

**Consequences** - Easier configuration

## D-002 Pin Elasticsearch 9.5.5

**Status** - Active. Need to pin the version in the ECK YAML and upgrade the current version

**Proposed** - Use the same Elasticsearch version across the research project

**Context** - Want local and Arbutus development results to agree. Currently 9.5.4 (arm64) is installed

**Decision** - Use Elasticsearch version 9.5.5

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

**Consequences** - 1,078,278 of 7,724,086 repositories kept (14%), with 181.7M of 283.9M events (64%). Median 26 events per repository, p99 2,188. The 1 TB tier (~67.5M events) needs about 37% of the filtered pool. A small amount of repositories are missed (i.e. bot heavy projects that are just above the event/actor line of 1000)

## D-005 Record model

**Status** - Closed

**Proposed** - Define a structure for records

**Context** - Use number-based keys for issues and PRs, snapshots from any event that touches the parent (latest event wins), all titles and bodies kept, pre-2024 entities kept with their real `created_at`.

**Decision** - To use the above ruleset

**Consequences** - Realistic storage costs for the experiment, no orphaned comments on PRs opened before 2024, comments refrence PRs by number only and issues can link to PRs in the same repository when a closing keyword is identified

--

## D-006 Mapping choices for S1 to S4

**Status** - Closed

**Proposed** - Use a curated bot list for observation, children copy non-test fields only and S4 has its own index set, with parent indexes (`pull_request`, `issue`, `person`) in `index.mode: lookup`

**Context** - Define these choice before mappings are coded in

**Decision** - Go ahead with the proposed decisions

**Consequences** - Reduce text dupilication, easier to load and drop strategies and information on bot activity

--

## D-007 Fold by repository buckets

**Status** - Closed

**Proposed** - Before folding, partition validated events into N buckets by `hash(repo_id)` on disk, then fold each bucket independently. People are merged across buckets at the end

**Context** - Performance considerations

**Decision** - Go with the buckets approach for now

**Consequences** - Every issue, PR, comment and review belongs to exactly one repository, so buckets never need each other, and memory is bounded by bucket size

--

## D-XXX

**Status** - TBC

**Proposed** - TBC

**Context** - TBC

**Decision** - TBC

**Consequences** - TBC

--

Format adapted from Michael Nygard's ADR Markdown [template](https://www.adr.zone/adr-template/nygard)
