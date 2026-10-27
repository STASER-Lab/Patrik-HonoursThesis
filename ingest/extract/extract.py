"""Extract GH Archive hourly files and verify each one is complete."""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import sys
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

BASE_URL = "https://data.gharchive.org"
CHUNK = 1 << 20  # 1 MiB

Fetch = Callable[[str], BinaryIO]


def hour_range(start: datetime, end: datetime) -> Iterator[datetime]:
    """Generator to round each hour for file naming, not zero-padded"""
    t = start.replace(minute=0, second=0, microsecond=0)
    while t < end:
        yield t
        t += timedelta(hours=1)


def file_name(hour: datetime) -> str:
    return f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"


def url_for(hour: datetime) -> str:
    return f"{BASE_URL}/{file_name(hour)}"


def is_complete_gzip(path: Path) -> bool:
    """True if the file decompresses fully. Catches truncated and corrupt files."""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(CHUNK):
                pass
        return True
    except (EOFError, OSError, zlib.error):
        return False


def default_fetch(url: str) -> BinaryIO:
    req = urllib.request.Request(url, headers={"User-Agent": "STASER-LAB (thesis research)"})
    return urllib.request.urlopen(req, timeout=60)


@dataclass
class Result:
    hour: datetime
    status: str  # ok | skipped | missing | failed
    bytes: int = 0
    detail: str = ""


def download_hour(
    hour: datetime,
    out_dir: Path,
    fetch: Fetch = default_fetch,
    retries: int = 3,
    backoff_s: float = 5.0,
) -> Result:
    dest = out_dir / file_name(hour)
    if dest.exists() and is_complete_gzip(dest):
        return Result(hour, "skipped", dest.stat().st_size, "already complete")

    part = dest.with_name(dest.name + ".part")
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with fetch(url_for(hour)) as resp, open(part, "wb") as f:
                while chunk := resp.read(CHUNK):
                    f.write(chunk)
            if is_complete_gzip(part):
                os.replace(part, dest)
                return Result(hour, "ok", dest.stat().st_size)
            last_error = "incomplete or corrupt gzip"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                part.unlink(missing_ok=True)
                return Result(hour, "missing", 0, "404 not found")
            last_error = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_error = f"{type(e).__name__}: {e}"
        part.unlink(missing_ok=True)
        if attempt < retries:
            time.sleep(backoff_s * attempt)
    return Result(hour, "failed", 0, last_error)


def append_manifest(manifest: Path, r: Result) -> None:
    new = not manifest.exists()
    with open(manifest, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["hour", "file", "status", "bytes", "detail", "logged_at"])
        w.writerow([r.hour.isoformat(), file_name(r.hour), r.status, r.bytes, r.detail,
                    datetime.now().isoformat(timespec="seconds")])


def parse_day_or_hour(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD or YYYY-MM-DDTHH, got {s!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download GH Archive hourly files")
    p.add_argument("--start", type=parse_day_or_hour, required=True, help="inclusive, e.g. 2024-01-10")
    p.add_argument("--end", type=parse_day_or_hour, required=True, help="exclusive, e.g. 2024-01-11")
    p.add_argument("--out", type=Path, default=Path("data/raw"))
    p.add_argument("--dry-run", action="store_true", help="print the URLs only")
    args = p.parse_args(argv)

    hours = list(hour_range(args.start, args.end))
    if args.dry_run:
        for h in hours:
            print(url_for(h))
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "manifest.csv"
    total, failed = 0, 0
    for i, h in enumerate(hours, 1):
        r = download_hour(h, args.out)
        append_manifest(manifest, r)
        total += r.bytes
        failed += r.status == "failed"
        print(f"[{i}/{len(hours)}] {file_name(h):28} {r.status:8} {r.bytes / 1e6:8.1f} MB {r.detail}")
    print(f"Done: {len(hours)} hours, {total / 1e9:.2f} GB on disk, {failed} failed. Manifest: {manifest}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
