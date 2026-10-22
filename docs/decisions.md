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

**Decision** - Keep a repository if it has >= 3 distinct actors, no single account produces > 80% of its events**, and <= 1,000 events per actor. Forks should also be filtered. This avoids using a third party tool like GitHub Search to filter the data since we would have our own.

**Consequences** - 1,078,278 of 7,724,086 repositories kept (14%), with 181.7M of 283.9M events (64%). Median 26 events per repository, p99 2,188. The 1 TB tier (~67.5M events) needs about 37% of the filtered pool. A small amount of repositories are missed (i.e. bot heavy projects that are just above the event/actor line of 1000)

## D-XXX Title

**Status** - TBC

**Proposed** - TBC

**Context** - TBC

**Decision** - TBC

**Consequences** - TBC

--

Format adapted from Michael Nygard's ADR Markdown [template](https://www.adr.zone/adr-template/nygard)
