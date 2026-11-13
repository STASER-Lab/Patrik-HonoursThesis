import gzip
import io
import urllib.error
from datetime import datetime

from ingest.extract import download_hours as dl

H = datetime(2024, 1, 10, 5)


def serve(monkeypatch, response):
    def fetch(url):
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)

    monkeypatch.setattr(dl, "fetch", fetch)


def test_hour_range_is_end_exclusive():
    hours = list(dl.hour_range(datetime(2024, 1, 10), datetime(2024, 1, 11)))
    assert len(hours) == 24
    assert hours[0].hour == 0 and hours[-1].hour == 23


def test_truncated_download_is_not_kept(tmp_path, monkeypatch):
    good = gzip.compress(b'{"id":"1"}\n' * 1000)
    serve(monkeypatch, good[: len(good) // 2])
    assert dl.download_hour(H, tmp_path).status == "failed"
    assert not list(tmp_path.iterdir())
    serve(monkeypatch, good)
    assert dl.download_hour(H, tmp_path).status == "ok"


def test_404_is_recorded_as_missing(tmp_path, monkeypatch):
    serve(monkeypatch, urllib.error.HTTPError("u", 404, "Not Found", {}, None))
    assert dl.download_hour(H, tmp_path).status == "missing"
