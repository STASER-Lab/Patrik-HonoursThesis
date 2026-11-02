# About

## Current state

The pipeline runs manually. It downloads GH Archive data, turns it into clean
records, builds all four layouts from them, loads them into Elasticsearch, and
measures loading speed and storage. The experiment cluster, tier
construction and query benchmarks are planned.

## End result

A decision guide that reads like:

> *If your questions look like X, store your data as Y, and deploy it as Z.*

X comes from the query kinds (single-entity, one-hop, history), Y
from the four layouts, and Z from the RQ3 configuration tests. Every
finding will be tied to a tier, a version and a hardware setup.

## Mention this work

If you use this work, please credit it (from [`CITATION.cff`](https://github.com/STASER-Lab/Patrik-HonoursThesis/blob/main/CITATION.cff)):

```text
P. Balazsy, "Scalable Elasticsearch infrastructure for software repository data,"
version 1.0. [Online]. Available: https://github.com/STASER-Lab/Patrik-HonoursThesis
```

Released under the [MIT License](https://github.com/STASER-Lab/Patrik-HonoursThesis/blob/main/LICENSE).

## Acknowledgements

This research is an honours thesis carried out in the STASER Lab.
