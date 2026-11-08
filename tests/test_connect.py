"""Client settings: env file, environment variables and the CA certificate."""

import pytest

from ingest.load.connect import settings_from

KEYS = ("ES_URL", "ES_API_KEY", "ES_USER", "ES_PASSWORD", "ES_CA_CERTS")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_env_file_from_elastic_start_local(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "ES_LOCAL_PORT=9200\n"
        "ES_LOCAL_URL=http://localhost:${ES_LOCAL_PORT}\n"
        'ES_LOCAL_PASSWORD="secret"\n'
    )
    s = settings_from(env)
    assert s["url"] == "http://localhost:9200"
    assert (s["user"], s["password"]) == ("elastic", "secret")
    assert s["ca_certs"] is None


def test_ca_certs_from_environment(monkeypatch):
    monkeypatch.setenv("ES_URL", "https://es.example:9200")
    monkeypatch.setenv("ES_CA_CERTS", "/certs/ca.crt")
    s = settings_from()
    assert s["url"] == "https://es.example:9200"
    assert s["ca_certs"] == "/certs/ca.crt"


def test_environment_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ES_LOCAL_URL=http://localhost:9200\nES_CA_CERTS=/file/ca.crt\n")
    monkeypatch.setenv("ES_CA_CERTS", "/env/ca.crt")
    assert settings_from(env)["ca_certs"] == "/env/ca.crt"
