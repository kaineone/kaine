# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 3 of biological-timing-and-dilation:

  * the vision sample rate is a first-class SUBJECTIVE rate decoupled from the
    workspace tick (``vision_sample_hz`` <-> ``capture_interval_s``), with the
    shipped 1 Hz default UNCHANGED;
  * ``scripts/timing_benchmark.py`` runs in a reduced/mock mode and emits the
    expected report structure (no GPU / no live services required in CI);
  * boot accepts ``vision_sample_hz`` as the clean rate expression.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from kaine.modules.topos.live import LiveCameraConfig

# scripts/ is not a package; load the benchmark module by path (mirrors
# tests/test_license_headers.py). Cached on the module so each test reuses it.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCH_PATH = _REPO_ROOT / "scripts" / "timing_benchmark.py"
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))


def _load_bench():
    spec = importlib.util.spec_from_file_location("timing_benchmark", _BENCH_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


bench = _load_bench()


# --------------------------------------------------------------------------
# 3.2 — vision sample rate as a first-class subjective rate (default unchanged)
# --------------------------------------------------------------------------


def test_default_vision_sample_hz_is_1hz_unchanged():
    cfg = LiveCameraConfig()
    # Behavior-preserving: shipped default stays 1.0 s / 1 Hz.
    assert cfg.capture_interval_s == 1.0
    assert cfg.vision_sample_hz == pytest.approx(1.0)


def test_vision_sample_hz_is_inverse_of_interval():
    assert LiveCameraConfig(capture_interval_s=0.1).vision_sample_hz == pytest.approx(10.0)
    assert LiveCameraConfig(capture_interval_s=0.5).vision_sample_hz == pytest.approx(2.0)


def test_interval_from_hz_roundtrips():
    assert LiveCameraConfig.interval_from_hz(10.0) == pytest.approx(0.1)
    assert LiveCameraConfig.interval_from_hz(2.0) == pytest.approx(0.5)


def test_non_positive_rates_rejected():
    with pytest.raises(ValueError):
        LiveCameraConfig.interval_from_hz(0.0)
    with pytest.raises(ValueError):
        LiveCameraConfig(capture_interval_s=0.0).vision_sample_hz


def test_boot_vision_sample_hz_takes_precedence_over_interval():
    from kaine.boot import make_topos

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    # vision_sample_hz wins when both keys are present.
    topos = make_topos(
        bus,
        {
            "capture_enabled": True,
            "capture_interval_s": 1.0,
            "vision_sample_hz": 5.0,
        },
    )
    cam = topos._live_camera  # type: ignore[attr-defined]
    assert cam is not None
    assert cam.config.capture_interval_s == pytest.approx(0.2)
    assert cam.config.vision_sample_hz == pytest.approx(5.0)


def test_boot_default_interval_unchanged_when_no_rate_key():
    from kaine.boot import make_topos

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    topos = make_topos(bus, {"capture_enabled": True})
    cam = topos._live_camera  # type: ignore[attr-defined]
    # Behavior-preserving: no rate key → the 1 Hz default holds.
    assert cam.config.capture_interval_s == pytest.approx(1.0)


# --------------------------------------------------------------------------
# 3.1/3.4 — the benchmark runs in reduced mode and emits the report structure
# --------------------------------------------------------------------------


def test_benchmark_stats_helpers():
    samples = [10.0, 20.0, 30.0, 40.0]
    stats = bench._stats_ms(samples)
    assert stats["n"] == 4
    assert stats["mean"] == pytest.approx(25.0)
    assert stats["max"] == 40.0
    assert bench._pct(samples, 0.0) == 10.0
    assert bench._pct(samples, 1.0) == 40.0


def test_benchmark_recommendations_stay_in_band():
    # A very cheap tick would imply a huge rate — clamped into the 3-10 band.
    rec_fast = bench._recommend_tick(1.0)
    assert bench.TICK_BAND_LOW_HZ <= rec_fast["recommended_hz"] <= bench.TICK_BAND_HIGH_HZ
    # A very expensive tick is clamped up to the band floor (never below).
    rec_slow = bench._recommend_tick(5000.0)
    assert rec_slow["recommended_hz"] == pytest.approx(bench.TICK_BAND_LOW_HZ)

    # Vision recommendation never exceeds the ~10 Hz biological target.
    rec_v = bench._recommend_vision(1.0)
    assert rec_v["recommended_hz"] <= bench.VISION_TARGET_HZ
    # No measurement → None recommendation, no fabricated number.
    assert bench._recommend_tick(float("nan"))["recommended_hz"] is None
    assert bench._recommend_vision(0.0)["recommended_hz"] is None


def test_benchmark_main_skips_both_cleanly(capsys):
    """With both sections skipped the harness emits the report structure and
    exits non-zero (nothing measured) — no fabricated numbers."""
    rc = asyncio.run(bench.main(["--skip-tick", "--skip-vision"]))
    out = capsys.readouterr().out
    assert "RECOMMENDATION" in out
    assert "NOT an entity boot" in out
    assert "NOT MEASURED" in out
    # Honest exit: nothing measured → non-zero.
    assert rc == 2


def test_benchmark_vision_skips_honestly_without_encoder(monkeypatch, capsys):
    """When the vision encoder is unavailable the section is SKIPPED with a
    reason, not faked."""
    # Force the encoder load to fail (simulating a missing model / extra).
    import kaine.modules.topos.encoder as enc

    async def _boom(self):
        raise RuntimeError("encoder model not present")

    monkeypatch.setattr(enc.DINOv2Encoder, "load", _boom)
    res = asyncio.run(bench._benchmark_vision({"topos": {}}, encodes=3))
    assert res["ran"] is False
    assert "encoder" in res["reason"].lower()
    assert res["samples_ms"] == []
