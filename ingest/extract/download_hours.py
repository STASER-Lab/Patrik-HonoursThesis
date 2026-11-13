"""Download GH Archive hourly files, keeping only files that decompress completely.

Complete files are skipped, so re-running retries only the failed hours.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import shutil
import sys
import urllib.error
import urllib.request
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

BASE_URL = "https://data.gharchive.org"


def hour_range(start: datetime, end: datetime) -> Iterator[datetime]:
    t = start.replace(minute=0, second=0, microsecond=0)
    while t < end:
        yield t
        t += timedelta(hours=1)


def file_name(hour: datetime) -> str:
    """GH Archive does not zero-pad the hour: 2024-01-10-5.json.gz"""
    return f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"


def url_for(hour: datetime) -> str:
    return f"{BASE_URL}/{file_name(hour)}"


def is_complete_gzip(path: Path) -> bool:
    """Decompress the whole file: truncation only surfaces at the end of the stream"""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except EOFError, OSError, zlib.error:
        return False


def fetch(url: str) -> BinaryIO:
    req = urllib.request.Request(url, headers={"User-Agent": "STASER-Lab"})
    return urllib.request.urlopen(req, timeout=60)


@dataclass
class Result:
    """`status` is ok, skipped (already downloaded), missing (404) or failed"""

    hour: datetime
    status: str
    size_bytes: int = 0
    detail: str = ""


def download_hour(hour: datetime, out_dir: Path) -> Result:
    """Download one hour into a .part file, renamed only once complete.

    A file under its final name is therefore always whole, so an existing one is
    skipped without checking it again. A 404 is a real gap in GH Archive, so it is
    reported as missing rather than failed.
    """
    dest = out_dir / file_name(hour)
    if dest.exists():
        return Result(hour, "skipped", dest.stat().st_size, "already downloaded")

    part = dest.with_name(dest.name + ".part")
    try:
        with fetch(url_for(hour)) as resp, open(part, "wb") as f:
            shutil.copyfileobj(resp, f)
        if not is_complete_gzip(part):
            return Result(hour, "failed", detail="incomplete or corrupt gzip")
        part.replace(dest)
        return Result(hour, "ok", dest.stat().st_size)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return Result(hour, "missing", detail="404 not found")
        return Result(hour, "failed", detail=f"HTTP {e.code}")
    except OSError as e:
        return Result(hour, "failed", detail=f"{type(e).__name__}: {e}")
    finally:
        part.unlink(missing_ok=True)


def append_manifest(manifest: Path, r: Result) -> None:
    new = not manifest.exists()
    with open(manifest, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["hour", "file", "status", "bytes", "detail", "logged_at"])
        w.writerow(
            [
                r.hour.isoformat(),
                file_name(r.hour),
                r.status,
                r.size_bytes,
                r.detail,
                datetime.now().isoformat(timespec="seconds"),
            ]
        )


def parse_day_or_hour(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD or YYYY-MM-DDTHH, got {s!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--start",
        type=parse_day_or_hour,
        required=True,
        help="inclusive, e.g. 2024-01-10",
    )
    p.add_argument(
        "--end",
        type=parse_day_or_hour,
        required=True,
        help="exclusive, e.g. 2024-01-11",
    )
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
        total += r.size_bytes
        failed += r.status == "failed"
        print(
            f"[{i}/{len(hours)}] {file_name(h):28} "
            f"{r.status:8} {r.size_bytes / 1e6:8.1f} MB {r.detail}"
        )
    print(
        f"Done: {len(hours)} hours, "
        f"{total / 1e9:.2f} GB on disk, {failed} failed (re-run to retry). "
        f"Manifest: {manifest}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
