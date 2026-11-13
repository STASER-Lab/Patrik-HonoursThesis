# Tutorial

This page covers setting up the project, running each stage, and how the experiments are organised. All commands run from the repository root.

## Requirements

| What | Version | Needed for |
|---|---|---|
| Python | 3.14 | Everything |
| Elasticsearch | 9.5.4 | Loading and benchmarking |
| Docker | Any recent | Running Elasticsearch locally |
| Google account | | BigQuery, only to rebuild the tier pool |

The experiments run on the Arbutus cloud: four Elasticsearch data nodes, plus a tooling server for ingest, Rally and monitoring. Nothing in the pipeline depends on that setup, though. Every stage also runs on a single machine against a local Elasticsearch, which is how it was developed. Only the amount of data that can be handled changes.

Rough resource needs:

| Resource | Need |
|---|---|
| Disk, raw data | About 100 MB per hourly file (2.5 GB per day). All of 2024 is about 900 GB. |
| Disk, outputs | Records take about half the size of the raw files. Bulk files are one more copy of the records per layout. |
| Memory | Transform holds one repository bucket at a time, so `--buckets` bounds memory rather than the tier size. |

## Getting started

Clone the repository, create a virtual environment and install the exact versions the project was tested with:

```bash
git clone https://github.com/STASER-Lab/Patrik-HonoursThesis.git
cd Patrik-HonoursThesis
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
pip install -e . --no-deps
pytest
```

For a local Elasticsearch, Elastic's `start-local` script runs it in Docker. Pin the same version as the experiments, and skip Kibana:

```bash
curl -fsSL https://elastic.co/start-local | sh -s -- -v 9.5.4 -esonly
```

This creates an `elastic-start-local/` folder whose `.env` file holds the connection details. Pass it to any command that talks to Elasticsearch with `--env-file elastic-start-local/.env`. To use another cluster, set `ES_URL` and either `ES_API_KEY` or `ES_USER` and `ES_PASSWORD` (plus `ES_CA_CERTS` for a self-signed certificate) instead.

The pipeline runs in this order:

```
profile → select → extract → transform → load → benchmark
```

Profile and select are already done for 2024, and the tier lists in `ingest/select/` are committed, so a run can start at extract.

### Profile and select

The queries in `ingest/profile/` profile GH Archive's data and build the pool the tiers are sampled from. Run them in the order below in the [BigQuery console](https://console.cloud.google.com/bigquery), which shows each query's size before it runs. The [sandbox](https://docs.cloud.google.com/bigquery/docs/sandbox) allows 1 TB of queries per month for free.

| Query | Result |
| --- | --- |
| `repository_ranking_2024.sql` | Save as table `repository_ranking_2024` |
| `repository_actors_2024.sql` | Save as table `repository_actors_2024` |
| `ranking_shape_2024.sql` | How skewed activity is |
| `volume_estimate_2024.sql` | Raw data size |
| `filter_rules_2024.sql` | Filter rules compared |
| `tier_pool_2024.sql` | Export as `ingest/select/pool.csv` |

Replace `your_project.your_dataset` with the location of the two saved tables. Only `tier_pool_2024.sql` feeds the pipeline. The others are the evidence behind the [Profile](profile.md) page.

To profile another period, change the year in the `FROM` clauses (for example `githubarchive.month.2023*`) and the table names. Then rebuild the tiers from the new pool:

```bash
python -m ingest.select.build_tiers ingest/select/pool.csv
```

This writes `10gb.txt`, `100gb.txt`, `1tb.txt` and `summary.json` to `ingest/select/`. The summary records the pool's checksum and each tier's size, so rebuilt lists can be compared with the committed ones.

### Ingest

**Extract.** Download a range of hours. The start is inclusive and the end exclusive, and either can be a day or a specific hour (`2024-01-10T05`):

```bash
python -m ingest.extract.download_hours --start 2024-01-10 --end 2024-01-11
```

Files go to `data/raw/` (change with `--out`), and every attempt is logged to `data/raw/manifest.csv`. If some hours fail, run the same command again: complete files are skipped. `--dry-run` only prints the URLs.

{: .note }
The tiers are drawn from repositories across all of 2024, so building a real tier needs the whole year downloaded. A single day is enough to try the pipeline.

**Transform.** Turn the raw files into records:

```bash
python -m ingest.transform.build_records data/raw --out data/records
```

| Option | Use |
|---|---|
| `--repos ingest/select/10gb.txt` | Keep only a tier's repositories. Without it, every repository is kept. |
| `--buckets N` | Fold N repository buckets one at a time to bound memory. 1 (the default) is fine for a day of data. Start around 16 for 100 GB and 128 for 1 TB, and measure. |

The command prints and saves `data/records/summary.json`: events read, rejected (and why), forks dropped, records written per entity, links found, and the share of records written by bots.

**Load.** Build the bulk files for every layout, then load one layout at a time:

```bash
python -m ingest.load.build_bulk data/records --layout all
python -m ingest.load.index_bulk --layout s1 --tier dev --recreate --env-file elastic-start-local/.env
```

| Option | Use |
|---|---|
| `--tier` | Names the indexes (for example `s1-dev-issue`), so tiers can sit side by side |
| `--recreate` | Replace the layout's indexes if they exist. Without it, the command stops rather than load into existing data. |
| `--shards`, `--replicas` | Index settings (defaults 1 and 0) |
| `--batch-docs` | Documents per bulk request (default 1,000) |

`index_bulk` prints the speed of each index and saves `data/results/load-<layout>-<tier>-<time>.json`. It exits with an error if any document was rejected.

### Benchmark

Check that every layout gives the right answers:

```bash
python -m benchmark.check_answers --tier dev --env-file elastic-start-local/.env
```

The first run for a tier picks the repositories to ask about and saves them in `benchmark/repositories.json`. Later runs reuse them. Use `--repick` after the tier's records change. `--queries`, `--layouts` and `--repos` narrow a run, for example `--queries q2,q4 --layouts s4`. Each result is PASS, FAIL or LIMIT, and the run fails only on FAIL. The full results go to `data/results/check-<tier>-<time>.json`.

Measure storage last, because it force-merges the indexes:

```bash
python -m benchmark.measure_storage --layout all --tier dev --env-file elastic-start-local/.env
```

Query speed (Rally) and update replay are under construction.

## Experiments

The experiments answer three research questions:

| RQ | Question | Answered by |
|---|---|---|
| RQ1 Capability | How can repository data be modelled in Elasticsearch, and which kinds of queries does each layout support? | Capability ratings for the seven queries |
| RQ2 Cost | What does each layout cost in speed and storage, and how do the costs scale as data grows and changes? | Load, storage, query and update benchmarks across three tiers |
| RQ3 Configuration | How should shards, replicas and nodes be configured for this data, and where does Elastic's standard guidance hold or break down? | Configuration benchmarks on the best layout |

### Test matrix

| Test | RQ | 10 GB | 100 GB | 1 TB |
|---|---|---|---|---|
| Capability ratings | 1 | S1–S4 | | |
| Ingestion speed | 2 | S1–S4 | S1–S4 | Finalists |
| Storage size | 2 | S1–S4 | S1–S4 | Finalists |
| Query speed | 2 | S1–S4 | S1–S4 | Finalists |
| Update replay | 2 | S1–S4 | S1–S4 | Finalists |
| Cluster configuration | 3 | | | Best read layout |

Finalists are the best layout for reading (lowest median p95 latency across the seven queries) and the best for updating (highest update throughput). If one layout wins both, the runner-up on the closer measure joins it. A layout that was cut still goes to 1 TB if it was closing the gap from 10 GB to 100 GB.

**Update replay** applies January to April 2025 events, in time order, to a loaded 2024 index. It shows what a change costs in each layout: one document in S1 and S4, a document plus every copy in S2, and a whole pull request in S3. Each repetition starts from the same 2024 index: an untouched, write-blocked copy is kept, and the replay runs on a fresh clone of it.

**Cluster configuration** changes one setting at a time from the 1 TB baseline (the best read layout on 4 nodes with 1 replica): node count (2 and 4), replicas (0 and 1), and shard count below, at and above Elastic's [recommended 10–50 GB per shard](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards). It runs at 1 TB because that is far beyond each node's memory cache, and it gives realistic shard sizes on both sides of the guidance.

### Metrics

| Metric | Unit | Source | RQ |
|---|---|---|---|
| Correctness | pass, fail or limit per query and layout | `check_answers` | 1 |
| Ingestion throughput | docs/s and MB/s | `index_bulk` | 2, 3 |
| Storage | index size ÷ raw size, merged | `measure_storage` | 2 |
| Query latency | p50, p95 and p99 in ms | Rally | 2, 3 |
| Query throughput | queries/s at a fixed number of clients | Rally | 2, 3 |
| Update throughput | events/s | Replay runner | 2 |
| Write amplification | documents written per event | Replay runner | 2 |
| Shard balance | largest ÷ median shard size | Elasticsearch stats | 3 |
| Resource use | CPU, heap, disk I/O and GC time per node | Monitoring | 2, 3 |

### Protocol

- Warm-up runs, then 5 repetitions of every test.
- Layouts are interleaved rather than run back to back, so a slow period on the hardware does not land on one layout.
- Cold runs (after a restart) and warm runs are reported separately.
- Reported: the median, p95, p99 and the spread between repetitions.
- The heap is fixed at 31 GB on every node. Elasticsearch and Java versions, heap size and machine type are recorded with every result.

### Hypotheses

Written before testing, and reported as confirmed or not:

1. S2 is fastest on one-hop reads (Q2, Q3), but slowest to update and largest on disk, because every child repeats its parent's fields.
2. S3 is fast for reads within one issue or PR, but has the most expensive updates, because changing any child re-indexes the whole document. On the largest repositories, it reaches Elasticsearch's nested limit.
3. S1 is the smallest and cheapest to update, but slowest on history and link queries (Q4 to Q7), because it joins in the client and needs the most requests.
4. S4 stores and updates like S1, but hits the ES\|QL row limit on the largest repositories for queries that return a row per PR or issue (Q2, Q4, Q6).
5. The gaps between layouts widen from 10 GB to 1 TB, as the data outgrows each node's memory.
6. For RQ3, shard sizes within Elastic's 10–50 GB guidance perform best, and going from 2 to 4 nodes improves query throughput at 1 TB.

## Tests

Run the test suite and the same style checks as GitHub Actions:

```bash
pytest
ruff format --check .
ruff check .
```

`ruff format .` and `ruff check --fix .` fix most style problems automatically. On every push to `main` and every pull request, GitHub Actions (`.github/workflows/tests.yml`) installs the locked versions and runs these three commands. A separate workflow (`pages.yml`) rebuilds this documentation whenever `documentation/` changes.

The tests check the parts that could silently change results, such as folding, links, mappings and the Python reference answers. They do not need Elasticsearch, so they cannot check that each layout returns the right answers. `check_answers` does that against a running cluster.
