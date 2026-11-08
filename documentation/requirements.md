# Requirements

What this project runs on, what it assumes, and where its limits are.

{: .note }
Status labels. *Working* means the code is in this repository and tested.
*Planned* means the design is fixed but the code is not in the repository yet.

## Stack

| Layer | Technology | Version | Status |
|---|---|---|---|
| Language | Python | 3.14+ | Working |
| Search engine | Elasticsearch | 9.5.4 (pinned) | Working |
| Elasticsearch client | [`elasticsearch`](https://pypi.org/project/elasticsearch/) (official Python client) | matches server | Working |
| Data source | [GH Archive](https://www.gharchive.org/) hourly event files | 2024/2025 | Working |
| Orchestration | [k3s](https://k3s.io/) (Kubernetes) and [Elastic Cloud on Kubernetes](https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s) (ECK) | | Planned |
| Infrastructure | [OpenTofu](https://opentofu.org/) and cloud-init on OpenStack ([Arbutus](https://uvic.ca/arbutus-cloud)) | | Planned |
| Benchmarking | [Elastic Rally](https://esrally.readthedocs.io/) with custom runners | | Planned |

## Compute resources

### Development

The ETL (extract, tranform, and load) pipeline run on a single machine. Load needs an Elasticsearch server,
which can be a local single-node install for small data.

| Resource | Need |
|---|---|
| Disk, raw data | About 2.5 GB per day of GH Archive data (about 100 MB per hourly file, compressed) |
| Disk, outputs | Records take about half the size of the compressed downloads (measured: 48 hourly files, 4.7 GB → 2.4 GB of records). Bulk files are one copy of the records per layout, slightly larger for S2 (copied fields) |
| Memory | Transform holds one repository bucket in memory at a time (`--buckets N`), plus all people, so RAM bounds the bucket size rather than the tier |

### Experiment cluster (Planned)

Dedicated lab hardware on Arbutus. (Specs subject to change)

| Machine | Role | vCPU | RAM | Disk |
|---|---|---|---|---|
| Control | k3s server, ECK operator | 8 | 32 GB | 200 GB |
| Data × 5 | One Elasticsearch node each, one per physical server | 16 each | 64 GB each (31 GB heap) | 2 TB each, local NVMe |
| Ingestion | Download, transform, bulk-load | 8 | 32 GB | 4.6 TB |
| Benchmark | Rally | 8 | 32 GB | 200 GB |
| Object storage | Snapshots | | | 8 TB |

## Prerequisites

To run the experiment

- Python 3.14+ and Git
- Internet access to `data.gharchive.org`
- An Elasticsearch 9.x server for the Load stage, reachable by URL with an
  API key or username and password, plus its CA certificate (`ES_CA_CERTS`)
  if it uses a self-signed one, as ECK does by default
- An Arbutus (OpenStack) project with an application credential (TBD)
- The lab's object storage bucket for snapshots (TBD)

## Limitations

- Public events only. GH Archive records public activity events, not a
  complete history. Edits and deletions of comments and reviews are never recorded.
- History starts in 2024. A "first-time contributor" means first seen since
  1 January 2024. Earlier activity is not visible.
- Transform holds one bucket of repositories in memory at a time
  (`--buckets N`, default 1 = everything in memory). People are kept for the
  whole run, since they appear in many repositories.
- Heuristics. Bot detection uses account type, a `[bot]` suffix, a login
  ending in "bot", and curated lists of known bots and of people whose login
  ends in "bot". Bots that post through a person's own account are missed. Issue–pull request links come from closing
  keywords in pull request text (e.g. "fixes #12"), and links to other
  repositories are skipped.
- One hardware setup. Results describe one cluster design. Different
  hardware may shift absolute numbers, though relative trade-offs should hold.
