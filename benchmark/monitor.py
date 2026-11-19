"""Run a command and record each Elasticsearch node's resource use while it runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ingest.load import connect

FILTER_PATH = [
    "nodes.*.name",
    "nodes.*.timestamp",
    "nodes.*.os.cpu.percent",
    "nodes.*.process.cpu.percent",
    "nodes.*.jvm.mem.heap_used_in_bytes",
    "nodes.*.jvm.mem.heap_max_in_bytes",
    "nodes.*.jvm.gc.collectors",
    "nodes.*.fs.io_stats.total",
]

# Cumulative since the node started: only differences between samples mean anything
COUNTERS = (
    "gc_young_ms",
    "gc_old_ms",
    "io_read_ops",
    "io_write_ops",
    "io_read_kb",
    "io_write_kb",
)


def _get(d: dict, *keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def flatten(node: dict) -> dict:
    gc = _get(node, "jvm", "gc", "collectors") or {}
    io = _get(node, "fs", "io_stats", "total") or {}
    heap = _get(node, "jvm", "mem", "heap_used_in_bytes")
    heap_max = _get(node, "jvm", "mem", "heap_max_in_bytes")
    return {
        "timestamp_ms": node.get("timestamp"),
        "cpu_os_pct": _get(node, "os", "cpu", "percent"),
        "cpu_es_pct": _get(node, "process", "cpu", "percent"),
        "heap_used_pct": None if not heap_max else round(100 * heap / heap_max, 1),
        "gc_young_ms": _get(gc, "young", "collection_time_in_millis"),
        "gc_old_ms": _get(gc, "old", "collection_time_in_millis"),
        "io_read_ops": io.get("read_operations"),
        "io_write_ops": io.get("write_operations"),
        "io_read_kb": io.get("read_kilobytes"),
        "io_write_kb": io.get("write_kilobytes"),
    }


def sample(es) -> dict:
    stats = es.nodes.stats(
        metric="os,process,jvm,fs", filter_path=",".join(FILTER_PATH)
    )
    return {n["name"]: flatten(n) for n in stats.get("nodes", {}).values()}


def summarise(samples: list[dict]) -> dict:
    per_node: dict[str, list[dict]] = {}
    for s in samples:
        for name, raw in s.get("nodes", {}).items():
            per_node.setdefault(name, []).append(raw)
    out = {}
    for name, rows in per_node.items():
        node = {"samples": len(rows)}
        for k in ("cpu_os_pct", "cpu_es_pct"):
            vals = [r[k] for r in rows if r.get(k) is not None]
            node[f"{k}_mean"] = round(sum(vals) / len(vals), 1) if vals else None
            node[f"{k}_max"] = max(vals) if vals else None
        heap = [r["heap_used_pct"] for r in rows if r.get("heap_used_pct") is not None]
        node["heap_used_pct_max"] = max(heap) if heap else None
        first, last = rows[0], rows[-1]
        for k in COUNTERS:
            a, b = first.get(k), last.get(k)
            node[f"{k}_total"] = (
                b - a if a is not None and b is not None and b >= a else None
            )
        out[name] = node
    return out


def run(
    command: list[str], label: str, es, interval: float = 5.0
) -> tuple[int, Path, Path]:
    connect.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
    samples_path = connect.RESULTS_DIR / f"monitor-{label}-{stamp}.ndjson"
    samples, errors = [], 0
    start = time.monotonic()
    proc = subprocess.Popen(command)

    with open(samples_path, "w") as out:
        out.write(
            json.dumps(
                {
                    "label": label,
                    "command": command,
                    "interval_s": interval,
                    "environment": connect.environment(es),
                }
            )
            + "\n"
        )

        def record() -> None:
            nonlocal errors
            row = {"t_s": round(time.monotonic() - start, 1)}
            try:
                nodes = sample(es)
            except Exception as e:  # a failed sample must not stop the run
                errors += 1
                row["error"] = f"{type(e).__name__}: {e}"
            else:
                row["nodes"] = nodes
                samples.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()

        try:
            record()
            while True:
                try:
                    code = proc.wait(timeout=interval)
                    break
                except subprocess.TimeoutExpired:
                    record()
        except KeyboardInterrupt:
            code = proc.wait()
        record()

    summary_path = connect.save_result(
        f"monitor-{label}",
        es,
        {
            "label": label,
            "command": command,
            "exit_code": code,
            "duration_s": round(time.monotonic() - start, 1),
            "interval_s": interval,
            "sample_errors": errors,
            "samples_file": samples_path.name,
            "nodes": summarise(samples),
        },
    )
    return code, samples_path, summary_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--label", required=True, help="names the result files")
    p.add_argument(
        "--interval", type=float, default=5.0, help="seconds between samples"
    )
    p.add_argument("--env-file", type=Path)
    p.add_argument(
        "command", nargs=argparse.REMAINDER, help="-- then the command to run"
    )
    args = p.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        p.error("give the command to run after --")
    if args.interval <= 0:
        p.error("--interval must be positive")
    code, samples_path, summary_path = run(
        command, args.label, connect.client(args.env_file), args.interval
    )
    print(f"Command exited {code}. Saved {samples_path} and {summary_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
