"""Connect to Elasticsearch, and save run results with the environment they ran in

Connection settings come from ES_URL, ES_API_KEY, ES_USER, ES_PASSWORD and ES_CA_CERTS,
or from elastic-start-local's .env file.
"""

from __future__ import annotations

import json
import os
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from elasticsearch import Elasticsearch

RESULTS_DIR = Path("data/results")


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip("\"'")
    # elastic-start-local's .env refers to other entries as ${NAME}
    for k, v in values.items():
        for ref, val in values.items():
            v = v.replace(f"${{{ref}}}", val)
        values[k] = v
    return values


def settings_from(env_file: Path | None = None) -> dict[str, str | None]:
    """Environment variables win over the env file. An API key wins over a user and
    password. With neither, the client connects without authentication."""
    f = read_env_file(env_file) if env_file else {}
    return {
        "url": os.getenv("ES_URL") or f.get("ES_LOCAL_URL") or "http://localhost:9200",
        "api_key": os.getenv("ES_API_KEY") or f.get("ES_LOCAL_API_KEY") or None,
        "user": os.getenv("ES_USER") or ("elastic" if env_file else None),
        "password": os.getenv("ES_PASSWORD") or f.get("ES_LOCAL_PASSWORD") or None,
        "ca_certs": os.getenv("ES_CA_CERTS") or f.get("ES_CA_CERTS") or None,
    }


def client(env_file: Path | None = None) -> Elasticsearch:
    s = settings_from(env_file)
    kw = {"ca_certs": s["ca_certs"]} if s["ca_certs"] else {}
    if s["api_key"]:
        kw["api_key"] = s["api_key"]
    elif s["user"] and s["password"]:
        kw["basic_auth"] = (s["user"], s["password"])
    return Elasticsearch(s["url"], **kw)


def environment(es) -> dict:
    info = es.info()["version"]
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": platform.node(),
        "python": platform.python_version(),
        "elasticsearch_client": version("elasticsearch"),
        "elasticsearch_server": info["number"],
        "elasticsearch_build": info.get("build_hash"),
    }


def save_result(name: str, es, data: dict) -> Path:
    """Write data/results/<name>-<time>.json and return its path"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"environment": environment(es), **data}, indent=2))
    return path
