import gzip
import io
import urllib.error
from datetime import datetime

from ingest.gharchive import download as dl


def gz(data: bytes) -> bytes:
    return gzip.compress(data)


def fake_fetch(responses):
    calls = []

    def fetch(url):
        calls.append(url)
        item = responses[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(item)

    fetch.calls = calls
    return fetch


H = datetime(2024, 1, 10, 5)


def test_url_hour_is_not_zero_padded():
    assert dl.url_for(H) == "https://data.gharchive.org/2024-01-10-5.json.gz"


def test_hour_range_is_end_exclusive():
    hours = list(dl.hour_range(datetime(2024, 1, 10), datetime(2024, 1, 11)))
    assert len(hours) == 24
    assert hours[0].hour == 0 and hours[-1].hour == 23


def test_download_ok_writes_file_and_no_part(tmp_path):
    r = dl.download_hour(H, tmp_path, fetch=fake_fetch([gz(b'{"id":"1"}\n')]))
    assert r.status == "ok"
    assert (tmp_path / "2024-01-10-5.json.gz").exists()
    assert not list(tmp_path.glob("*.part"))


def test_existing_complete_file_is_skipped(tmp_path):
    (tmp_path / "2024-01-10-5.json.gz").write_bytes(gz(b"x\n"))
    fetch = fake_fetch([])
    r = dl.download_hour(H, tmp_path, fetch=fetch)
    assert r.status == "skipped" and fetch.calls == []


def test_truncated_download_is_retried(tmp_path):
    good = gz(b'{"id":"1"}\n' * 1000)
    fetch = fake_fetch([good[: len(good) // 2], good])
    r = dl.download_hour(H, tmp_path, fetch=fetch, backoff_s=0)
    assert r.status == "ok" and len(fetch.calls) == 2


def test_404_is_missing_not_retried(tmp_path):
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    fetch = fake_fetch([err])
    r = dl.download_hour(H, tmp_path, fetch=fetch, backoff_s=0)
    assert r.status == "missing" and len(fetch.calls) == 1


def test_gives_up_after_retries(tmp_path):
    fetch = fake_fetch([ConnectionError("reset")] * 3)
    r = dl.download_hour(H, tmp_path, fetch=fetch, retries=3, backoff_s=0)
    assert r.status == "failed" and len(fetch.calls) == 3
    assert not list(tmp_path.iterdir())


def test_manifest_has_header_once(tmp_path):
    m = tmp_path / "manifest.csv"
    dl.append_manifest(m, dl.Result(H, "ok", 10))
    dl.append_manifest(m, dl.Result(H, "ok", 10))
    lines = m.read_text().splitlines()
    assert lines[0].startswith("hour,") and len(lines) == 3
