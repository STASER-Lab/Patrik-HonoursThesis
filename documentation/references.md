# References

Informal references for the tools, data and examples used in this documentation and project, along with the conventions the code follows.

## Acknowledgements

- STASER-Lab, for resources and guidance
- The Arbutus cloud, for the computing cluster

## Data and tools

| Resource | Used for |
|---|---|
| [GH Archive](https://www.gharchive.org/) | Public GitHub activity, one compressed JSON file per hour |
| [Google BigQuery sandbox](https://docs.cloud.google.com/bigquery/docs/sandbox) | Profiling GH Archive and building the tier pool |
| [CHAOSS metrics](https://chaoss.community/) | The basis of the seven benchmark queries |
| [Elasticsearch](https://www.elastic.co/docs) | Storing and querying each layout |
| [Elasticsearch shard sizing guidance](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/size-shards) | The 10–50 GB per shard tested in RQ3 |
| [start-local](https://github.com/elastic/start-local) | Running Elasticsearch locally in Docker |
| [Rally](https://esrally.readthedocs.io/) | Benchmarking query speed |
| [Elastic Cloud on Kubernetes (ECK)](https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s) | Running Elasticsearch on the cluster |
| [k3s](https://k3s.io/) | Lightweight Kubernetes |
| [OpenTofu](https://opentofu.org/) | Creating the cluster's machines on Arbutus |
| [Medallion Architecture](https://www.databricks.com/glossary/medallion-architecture) | The bronze, silver and gold layers of the ingest process |
| [Just the Docs](https://just-the-docs.com/) | This documentation site |
| [Ruff](https://docs.astral.sh/ruff/) | Python formatting and linting |

## Conventions

**Code**

- Python is formatted and linted with Ruff, using its defaults.
- File and folder names are lowercase, with underscores (`build_records.py`, `profile/`). Documentation pages are single lowercase words.
- Runnable scripts are named verb first, then what they act on: `build_tiers`, `download_hours`, `build_records`, `build_bulk`, `index_bulk`, `check_answers`, `measure_storage`.
- IDs are uppercase in text and lowercase in code and file names: Q1 and `q1.py`, S1 and `s1`, RQ1.
- Components are grouped by their role: `ingest/` holds the stages in the order they run, and `benchmark/` holds the tools that produce results.

**Comments**

- Docstrings give a clear, simple and precise description of what the code does and what it requires.
- Inline comments appear only where the code is not obvious and its purpose cannot easily be inferred.

**Tests**

- One test file per component, in `tests/`.
- A test is written when a bug could silently change results. Failures that would be loud anyway are not tested.

**GitHub workflow**

| Item | Example |
|---|---|
| PR and issue titles | Improve code readability and maintainability |
| PR and issue descriptions | Review and refactor the existing codebase to improve readability, maintainability, and consistency. |
| Branches | `improve-code-readability` |
| Commit messages | Clean up codebase and reduce complexity |

## AI assistants

Claude is primarily used outside of the codebase to generate code, refactor and debug. Other LLMs, such as ChatGPT and Gemini, are sometimes used to review code. All AI-assisted work is reviewed and tested before it is committed, and code that affects results is checked against the Python reference answers. The research decisions, and responsibility for all content, remain with the author.

## Other decisions

**Kubernetes over Docker.** The original plan was Docker Compose. Kubernetes (k3s with ECK) lets one control machine manage every node, which makes the cluster easier to configure and resize between experiments. See [Cluster](design.md#cluster-under-construction).

**Repository filtering.** Based on the BigQuery profile, a repository is kept only if it has at least 3 distinct accounts, no single account makes more than 80% of its events, and it averages at most 1,000 events per account. See [Profiling](design.md#profiling).
