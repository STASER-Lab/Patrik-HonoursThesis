"""Tier construction: nesting, the 10% cap, band shares and repeatability."""

import json
import random

import pytest

from ingest.extract.tiers import band, build, main

TIERS = {"small": 2_000, "large": 20_000}


@pytest.fixture
def pool():
    rng = random.Random(7)
    pool = {i: rng.choice([3, 5, 8, 20, 40, 90, 300]) for i in range(2_000)}
    pool[9_000] = 1_500
    pool[9_001] = 50_000
    return pool


def test_band_is_powers_of_ten():
    assert [band(e) for e in (3, 9, 10, 99, 100, 5_000)] == [0, 0, 1, 1, 2, 3]


def test_tiers_are_nested_capped_and_reach_their_target(pool):
    tiers = build(pool, TIERS)
    assert tiers["small"] <= tiers["large"]
    for name, target in TIERS.items():
        events = [pool[r] for r in tiers[name]]
        assert sum(events) >= target
        assert max(events) <= 0.1 * target
    assert 9_000 not in tiers["small"] and 9_001 not in tiers["large"]


def test_bands_keep_their_share_of_events(pool):
    # without the two outliers, which test the cap above
    pool = {r: e for r, e in pool.items() if r < 9_000}
    tiers = build(pool, TIERS)
    allowed = {r: e for r, e in pool.items() if e <= 0.1 * TIERS["large"]}
    for b in {band(e) for e in allowed.values()}:
        share_pool = sum(e for e in allowed.values() if band(e) == b) / sum(
            allowed.values()
        )
        picked = [pool[r] for r in tiers["large"]]
        share_tier = sum(e for e in picked if band(e) == b) / sum(picked)
        assert share_tier == pytest.approx(share_pool, abs=0.02)


def test_same_seed_same_tiers_and_pool_too_small(pool):
    assert build(pool, TIERS, seed=1) == build(pool, TIERS, seed=1)
    assert build(pool, TIERS, seed=1) != build(pool, TIERS, seed=2)
    with pytest.raises(ValueError):
        build(pool, {"huge": 10_000_000})


def test_main_writes_lists_and_summary(tmp_path, pool, monkeypatch):
    monkeypatch.setattr("ingest.extract.tiers.TIERS", TIERS)
    csv = tmp_path / "pool.csv"
    csv.write_text("repo_id,events\n" + "".join(f"{r},{e}\n" for r, e in pool.items()))
    assert main([str(csv), "--out", str(tmp_path / "tiers")]) == 0
    small = (tmp_path / "tiers" / "small.txt").read_text().split()
    summary = json.loads((tmp_path / "tiers" / "summary.json").read_text())
    assert summary["tiers"]["small"]["repos"] == len(small)
    assert summary["pool"]["repos"] == len(pool)
