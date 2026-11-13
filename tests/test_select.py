import random

import pytest

from ingest.select.build_tiers import band, build

TIERS = {"small": 2_000, "large": 20_000}


@pytest.fixture
def pool():
    rng = random.Random(7)
    base = {i: rng.choice([3, 5, 8, 20, 40, 90, 300]) for i in range(2_000)}
    return base | {9_000: 1_500, 9_001: 50_000}


def test_band_is_powers_of_ten():
    assert [band(e) for e in (3, 9, 10, 99, 100, 5_000)] == [0, 0, 1, 1, 2, 3]


def test_tiers_are_nested_capped_and_reach_their_target(pool):
    tiers = build(pool, TIERS)
    assert tiers["small"] <= tiers["large"]
    for name, target in TIERS.items():
        events = [pool[r] for r in tiers[name]]
        assert sum(events) >= target and max(events) <= 0.1 * target
    assert 9_000 not in tiers["small"] and 9_001 not in tiers["large"]


def test_bands_keep_their_share_of_events(pool):
    pool = {r: e for r, e in pool.items() if r < 9_000}
    picked = [pool[r] for r in build(pool, TIERS)["large"]]
    vals = list(pool.values())
    for b in {band(e) for e in vals}:
        share_pool = sum(e for e in vals if band(e) == b) / sum(vals)
        share_tier = sum(e for e in picked if band(e) == b) / sum(picked)
        assert share_tier == pytest.approx(share_pool, abs=0.02)


def test_same_seed_same_tiers_and_pool_too_small(pool):
    assert build(pool, TIERS, seed=1) == build(pool, TIERS, seed=1)
    assert build(pool, TIERS, seed=1) != build(pool, TIERS, seed=2)
    with pytest.raises(ValueError):
        build(pool, {"huge": 10_000_000})
