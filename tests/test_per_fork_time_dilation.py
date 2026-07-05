# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 4: per-fork subjective-time profile.

Pins the hard invariants of the per-fork-time-dilation change:

  * the typed profile parses/validates metadata['timing'] (valid / absent→None /
    time_scale<=0 runnable → loud error / bad rate → error);
  * ForkManager.fork() round-trips a timing profile through the EXISTING
    metadata path (no merge/assimilation change);
  * apply_fork_timing_profile sets the EntityClock scale + the cycle rates via
    the existing seams, and is a no-op for a profile-less fork;
  * a profile-less fork changes NEITHER the clock scale NOR the cycle rates
    (the behavior-preserving proof);
  * POST /forks with time_scale stores it in metadata; GET /forks.json surfaces
    the timing profile read-only.
"""
from __future__ import annotations

import pytest

from kaine.cycle.fork_timing import apply_fork_timing_profile
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.lifecycle.timing_profile import (
    ForkTimingProfile,
    InvalidForkTimingProfile,
    build_timing_metadata,
    fork_timing_profile,
)


# ---------------------------------------------------------------------------
# 4.1 — profile parse / validate
# ---------------------------------------------------------------------------


def test_parse_valid_profile_full():
    snap = ForkSnapshot(
        metadata={
            "timing": {
                "time_scale": 2.0,
                "processing_rate_hz": 12.0,
                "experiential_rate_hz": 3.333,
                "vision_sample_hz": 10.0,
            }
        }
    )
    profile = fork_timing_profile(snap)
    assert profile == ForkTimingProfile(
        time_scale=2.0,
        processing_rate_hz=12.0,
        experiential_rate_hz=3.333,
        vision_sample_hz=10.0,
    )


def test_parse_valid_profile_scale_only():
    profile = fork_timing_profile({"timing": {"time_scale": 0.5}})
    assert profile is not None
    assert profile.time_scale == 0.5
    assert profile.processing_rate_hz is None
    assert profile.experiential_rate_hz is None
    assert profile.vision_sample_hz is None


def test_parse_absent_timing_returns_none():
    assert fork_timing_profile({}) is None
    assert fork_timing_profile({"shed": []}) is None
    assert fork_timing_profile(ForkSnapshot()) is None


def test_parse_empty_timing_dict_returns_none():
    # An explicitly-empty timing dict carries no profile — treat as absent.
    assert fork_timing_profile({"timing": {}}) is None


@pytest.mark.parametrize("bad_scale", [0, 0.0, -1.0, -0.5])
def test_parse_nonpositive_time_scale_raises(bad_scale):
    with pytest.raises(InvalidForkTimingProfile):
        fork_timing_profile({"timing": {"time_scale": bad_scale}})


def test_parse_timing_without_time_scale_raises():
    # A rate override but no time_scale is not a runnable profile.
    with pytest.raises(InvalidForkTimingProfile):
        fork_timing_profile({"timing": {"processing_rate_hz": 10.0}})


def test_parse_non_numeric_time_scale_raises():
    with pytest.raises(InvalidForkTimingProfile):
        fork_timing_profile({"timing": {"time_scale": "fast"}})


@pytest.mark.parametrize(
    "field", ["processing_rate_hz", "experiential_rate_hz", "vision_sample_hz"]
)
def test_parse_nonpositive_rate_override_raises(field):
    with pytest.raises(InvalidForkTimingProfile):
        fork_timing_profile({"timing": {"time_scale": 2.0, field: 0.0}})


def test_parse_timing_not_a_mapping_raises():
    with pytest.raises(InvalidForkTimingProfile):
        fork_timing_profile({"timing": [1, 2, 3]})


def test_build_timing_metadata_only_provided_keys():
    md = build_timing_metadata(time_scale=2.0, vision_sample_hz=10.0)
    assert md == {"timing": {"time_scale": 2.0, "vision_sample_hz": 10.0}}
    # No keys provided → empty dict (no timing key, behavior-preserving).
    assert build_timing_metadata() == {}


def test_build_timing_metadata_rejects_rate_without_scale():
    with pytest.raises(InvalidForkTimingProfile):
        build_timing_metadata(processing_rate_hz=10.0)


def test_profile_to_metadata_roundtrips():
    profile = fork_timing_profile({"timing": {"time_scale": 2.0}})
    assert profile is not None
    assert profile.to_metadata() == {"time_scale": 2.0}
    again = fork_timing_profile({"timing": profile.to_metadata()})
    assert again == profile


# ---------------------------------------------------------------------------
# 4.2 — fork() round-trips a timing profile through metadata
# ---------------------------------------------------------------------------


class _FakeMod:
    name = "soma"

    def serialize(self):
        return {"wellness": 0.9}

    def deserialize(self, state):
        pass


class _FakeReg:
    def all_modules(self):
        return iter([_FakeMod()])


def test_fork_roundtrips_timing_profile(tmp_path):
    fm = ForkManager(tmp_path)
    parent = fm.snapshot(_FakeReg(), label="root")
    child = fm.fork(
        parent.id,
        label="dilated",
        metadata=build_timing_metadata(time_scale=2.0, processing_rate_hz=12.0),
    )
    # The profile survives the snapshot round-trip on disk.
    reloaded = fm.load(child.id)
    profile = fork_timing_profile(reloaded)
    assert profile is not None
    assert profile.time_scale == 2.0
    assert profile.processing_rate_hz == 12.0


def test_fork_without_timing_has_no_profile(tmp_path):
    fm = ForkManager(tmp_path)
    parent = fm.snapshot(_FakeReg(), label="root")
    child = fm.fork(parent.id, label="plain")
    assert fork_timing_profile(fm.load(child.id)) is None


# ---------------------------------------------------------------------------
# 4.3 — apply_fork_timing_profile via injected fakes
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, scale=1.0):
        self._scale = scale

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, value):
        self._scale = value


class _FakeCycle:
    def __init__(self):
        self.processing_rate_hz = 10.0
        self.experiential_rate_hz = 10.0

    def set_processing_rate(self, hz):
        self.processing_rate_hz = hz

    def set_experiential_rate(self, hz):
        self.experiential_rate_hz = hz


class _FakeCamera:
    def __init__(self):
        self.vision_sample_hz = 1.0

    def set_vision_sample_hz(self, hz):
        self.vision_sample_hz = hz


def test_apply_sets_scale_and_rates():
    clock = _FakeClock(scale=1.0)
    cycle = _FakeCycle()
    camera = _FakeCamera()
    profile = fork_timing_profile(
        {
            "timing": {
                "time_scale": 2.0,
                "processing_rate_hz": 12.0,
                "experiential_rate_hz": 4.0,
                "vision_sample_hz": 10.0,
            }
        }
    )
    summary = apply_fork_timing_profile(
        profile, clock, cycle, vision_rate_sink=camera
    )
    assert clock.scale == 2.0
    assert cycle.processing_rate_hz == 12.0
    assert cycle.experiential_rate_hz == 4.0
    assert camera.vision_sample_hz == 10.0
    assert summary["applied"] is True
    assert summary["time_scale"] == 2.0
    assert summary["vision_sample_hz"] == 10.0


def test_apply_scale_only_leaves_rates():
    clock = _FakeClock(scale=1.0)
    cycle = _FakeCycle()
    profile = fork_timing_profile({"timing": {"time_scale": 0.5}})
    summary = apply_fork_timing_profile(profile, clock, cycle)
    assert clock.scale == 0.5
    # No rate override → the cycle's rates are untouched.
    assert cycle.processing_rate_hz == 10.0
    assert cycle.experiential_rate_hz == 10.0
    assert summary["processing_rate_hz"] is None


def test_apply_vision_via_topos_handle():
    # The handle is the "Topos module" exposing a live_camera attr, not the
    # camera directly — the seam resolves it.
    clock = _FakeClock()
    cycle = _FakeCycle()
    camera = _FakeCamera()

    class _FakeTopos:
        def __init__(self, cam):
            self.live_camera = cam

    profile = fork_timing_profile(
        {"timing": {"time_scale": 2.0, "vision_sample_hz": 8.0}}
    )
    summary = apply_fork_timing_profile(
        profile, clock, cycle, vision_rate_sink=_FakeTopos(camera)
    )
    assert camera.vision_sample_hz == 8.0
    assert summary["vision_sample_hz"] == 8.0


def test_apply_vision_unreachable_is_honest_not_faked():
    clock = _FakeClock()
    cycle = _FakeCycle()
    profile = fork_timing_profile(
        {"timing": {"time_scale": 2.0, "vision_sample_hz": 8.0}}
    )
    # No vision sink available — the override is honestly recorded as unapplied.
    summary = apply_fork_timing_profile(profile, clock, cycle, vision_rate_sink=None)
    assert clock.scale == 2.0
    assert summary["vision_sample_hz"] is None
    assert summary["vision_sample_hz_unapplied"] == 8.0


# ---------------------------------------------------------------------------
# 4.5 — behavior-preserving: a profile-less fork changes nothing
# ---------------------------------------------------------------------------


def test_apply_none_profile_is_noop():
    clock = _FakeClock(scale=1.0)
    cycle = _FakeCycle()
    camera = _FakeCamera()
    summary = apply_fork_timing_profile(None, clock, cycle, vision_rate_sink=camera)
    assert clock.scale == 1.0
    assert cycle.processing_rate_hz == 10.0
    assert cycle.experiential_rate_hz == 10.0
    assert camera.vision_sample_hz == 1.0
    assert summary["applied"] is False


def test_profileless_fork_end_to_end_is_behavior_preserving(tmp_path):
    """A fork with no timing profile, restored + applied, mutates nothing."""
    fm = ForkManager(tmp_path)
    parent = fm.snapshot(_FakeReg(), label="root")
    child = fm.fork(parent.id, label="plain")

    clock = _FakeClock(scale=1.0)
    cycle = _FakeCycle()
    camera = _FakeCamera()

    # The seam reads the (absent) profile and is a no-op.
    profile = fork_timing_profile(fm.load(child.id))
    assert profile is None
    apply_fork_timing_profile(profile, clock, cycle, vision_rate_sink=camera)

    assert clock.scale == 1.0
    assert cycle.processing_rate_hz == 10.0
    assert cycle.experiential_rate_hz == 10.0
    assert camera.vision_sample_hz == 1.0


# ---------------------------------------------------------------------------
# Real seams: the EntityClock + LiveCamera the runtime actually uses.
# ---------------------------------------------------------------------------


def test_apply_against_real_entity_clock_and_camera():
    from kaine.entity_clock import EntityClock
    from kaine.modules.topos.live import LiveCamera, LiveCameraConfig

    clock = EntityClock(scale=1.0)

    async def _sink(_):  # pragma: no cover - never called in this test
        return None

    camera = LiveCamera(_sink, config=LiveCameraConfig(capture_interval_s=1.0))
    cycle = _FakeCycle()
    profile = fork_timing_profile(
        {"timing": {"time_scale": 3.0, "vision_sample_hz": 5.0}}
    )
    apply_fork_timing_profile(profile, clock, cycle, vision_rate_sink=camera)
    assert clock.scale == 3.0
    # vision_sample_hz 5.0 → capture_interval_s 0.2 on the live config.
    assert camera.config.vision_sample_hz == pytest.approx(5.0)
    assert camera.config.capture_interval_s == pytest.approx(0.2)
