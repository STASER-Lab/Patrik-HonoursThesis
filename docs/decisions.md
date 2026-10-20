# Decision Records

## D-001 k8s instead of Docker

**Status** - Closed

**Proposed** - Ship Elasticsearch with k3s and Elastic Cloud on Kubernetes (ECK)

**Context** - The original plan was to use Docker Compose

**Decision** - Use k3s and ECK beceause one control VM can manage every node

**Consequences** - Easier configuration

--

## D-002 Pin Elasticsearch 9.5.5

**Status** - Active. Need to pin the version in the ECK YAML and upgrade the current version

**Proposed** - Use the same Elasticsearch version across the research project

**Context** - Want local and Arbutus development results to agree. Currently 9.5.4 (arm64) is installed

**Decision** - Use Elasticsearch version 9.5.5

**Consequences** - Consistent results across local and Arbutus. Also helps reproducibility

--

## D-XXX Title

**Status** - TBC

**Proposed** - TBC

**Context** - TBC

**Decision** - TBC

**Consequences** - TBC

--

Format adapted from Michael Nygard's ADR Markdown [template](https://www.adr.zone/adr-template/nygard)
