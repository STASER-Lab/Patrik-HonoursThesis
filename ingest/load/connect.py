"""Build an Elasticsearch client from environment variables or an env file"""

from __future__ import annotations

import os
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    # resolve ${VAR} references used by elastic-start-local
    for k, v in values.items():
        for ref, val in values.items():
            v = v.replace("${" + ref + "}", val)
        values[k] = v
    return values


def settings_from(env_file: Path | None = None) -> dict[str, str | None]:
    src = dict(os.environ)
    if env_file:
        f = read_env_file(env_file)
        src.setdefault("ES_URL", f.get("ES_LOCAL_URL", ""))
        src.setdefault("ES_API_KEY", f.get("ES_LOCAL_API_KEY", ""))
        src.setdefault("ES_USER", "elastic")
        src.setdefault("ES_PASSWORD", f.get("ES_LOCAL_PASSWORD", ""))
    return {
        "url": src.get("ES_URL") or "http://localhost:9200",
        "api_key": src.get("ES_API_KEY") or None,
        "user": src.get("ES_USER") or None,
        "password": src.get("ES_PASSWORD") or None,
    }


def client(env_file: Path | None = None):
    from elasticsearch import (
        Elasticsearch,
    )  # imported here so tests don't need the package

    s = settings_from(env_file)
    if s["api_key"]:
        return Elasticsearch(s["url"], api_key=s["api_key"])
    if s["user"] and s["password"]:
        return Elasticsearch(s["url"], basic_auth=(s["user"], s["password"]))
    return Elasticsearch(s["url"])
