# Architecture

The project has two parts. First, a pipeline turns raw GitHub activity into
Elasticsearch indexes. Then a cluster stores and serves them during
experiments.

## The pipeline

The pipeline follows the Medallion Architecture where data moves through three layers increasing in quality (bronze, silver, and gold). Every layer is written to disk, so each stage can be rerun or inspected on its own. Continue reading to follow the data flow from end to end:

<img alt="Medallion Architecture" src="Medallion_Architecture.png?raw=true" width="800">

Three rules hold across the pipeline:

1. One source of truth. All four layouts are built from the same Silver
   records, so differences in results come from the layout, not the data.
2. Stable keys. Every record's ID comes from the data itself
   (e.g. `12345/42` for issue 42 in repository 12345). Loading twice
   overwrites instead of duplicating.
3. Every stage reports. Each stage logs a manifest or summary of what it
   kept, rejected and why.

### Code layout

| Folder | Stage |
|---|---|
| [`ingest/extract/`](https://github.com/STASER-Lab/Patrik-HonoursThesis/tree/main/ingest/extract) | Extract |
| [`ingest/transform/`](https://github.com/STASER-Lab/Patrik-HonoursThesis/tree/main/ingest/transform) | Transform |
| [`ingest/load/`](https://github.com/STASER-Lab/Patrik-HonoursThesis/tree/main/ingest/load) | Load |
| [`tests/`](https://github.com/STASER-Lab/Patrik-HonoursThesis/tree/main/tests) | Unit tests for all three stages |

### Set up

From the repository root:

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Run the whole pipeline

Every command runs from the repository root. This example uses one day of data
and the `dev` tier.

```bash
# Bronze
python -m ingest.extract.download --start 2024-01-10 --end 2024-01-11

# Silver
python -m ingest.transform.build_records data/raw --out data/records

# Gold (repeat the last three lines if you want to capture the remaining three strategies)
python -m ingest.load.bulk data/records --strategy all
python -m ingest.load.create_indexes --strategy s1 --tier dev --env-file elastic-start-local/.env
python -m ingest.load.index          --strategy s1 --tier dev --env-file elastic-start-local/.env
python -m ingest.load.stats          --strategy s1 --tier dev --env-file elastic-start-local/.env
```

## The cluster (Planned)

The experiment cluster is rebuilt from files in this repository, in four layers:

| Layer | Tool | Job |
|---|---|---|
| 1. Machines | OpenTofu | Creates the VMs, private network and firewall on Arbutus. Data VMs are forced onto different physical servers. |
| 2. First boot | cloud-init | Installs updates, sets the kernel limit Elasticsearch needs, mounts data disks. |
| 3. Kubernetes | k3s | Joins the VMs into one cluster and labels the data VMs. |
| 4. Elasticsearch | ECK | Runs a 5-node Elasticsearch cluster from one YAML file, with the version pinned. |
