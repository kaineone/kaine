# SPDX-License-Identifier: Apache-2.0
"""Tests for playlist-sleep-pause: Hypnos sleep freezes the shared playlist
clock and restores the pre-sleep perception locus on wake.

Uses the _FakeClock pattern (manually advanced monotonic clock) — no real
sleep, no real time. perception_state paths are stubbed via monkeypatch so no
real state files are touched (except the flags-only audit, which writes a
throwaway tmp_path file)."""


import pytest

from types import SimpleNamespace


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _bare_hypnos(desired_path, clock=None):
    """Build a Hypnos instance without the full constructor: only the
    suspend/restore seam's attributes are under test here."""
    from kaine.modules.hypnos.module import Hypnos

    h = object.__new__(Hypnos)
    h._perception_desired_path = desired_path
    h._playlist_clock = clock
    h._pre_sleep_locus = None
    return h


def _stub_perception_state(monkeypatch, locus, written):
    from kaine import perception_state as ps

    monkeypatch.setattr(
        ps, "read_desired", lambda path=None: SimpleNamespace(locus=locus)
    )
    monkeypatch.setattr(
        ps,
        "write_desired_locus",
        lambda locus, path=None: written.append(locus),
    )
    return ps


def test_suspend_pauses_clock_and_restores_pre_sleep_virtual_locus(
    tmp_path, monkeypatch
):
    from kaine.modules.topos.feed import PlaylistClock

    written = []
    _stub_perception_state(monkeypatch, "virtual", written)

    clock = PlaylistClock(1, clock=_FakeClock())
    clock.start()
    clk = clock._clock
    clk.t = 1.0
    h = _bare_hypnos(tmp_path / "desired.json", clock=clock)

    h._suspend_perception()
    assert written == ["off"]
    assert clock.paused
    clk.t = 100.0  # a long sleep: elapsed stays frozen at the pause point
    assert clock.elapsed() == 1.0

    h._restore_perception()
    assert written == ["off", "virtual"]
    assert not clock.paused
    assert clock.elapsed() == 1.0  # resumes at the pause point
    assert h._pre_sleep_locus is None


def test_pre_sleep_physical_locus_is_restored(tmp_path, monkeypatch):
    written = []
    _stub_perception_state(monkeypatch, "physical", written)
    h = _bare_hypnos(tmp_path / "desired.json")
    h._suspend_perception()
    h._restore_perception()
    assert written == ["off", "physical"]


def test_restore_without_suspend_falls_back_to_physical(tmp_path, monkeypatch):
    written = []
    _stub_perception_state(monkeypatch, "virtual", written)
    h = _bare_hypnos(tmp_path / "desired.json")
    # Suspend never ran: nothing remembered → old behavior, defensively.
    h._restore_perception()
    assert written == ["physical"]


def test_unknown_pre_sleep_locus_is_coerced_to_physical(tmp_path, monkeypatch):
    written = []
    _stub_perception_state(monkeypatch, "weird-value", written)
    h = _bare_hypnos(tmp_path / "desired.json")
    h._suspend_perception()
    h._restore_perception()
    assert written == ["off", "physical"]


def test_missing_clock_is_an_honest_noop(tmp_path, monkeypatch):
    written = []
    _stub_perception_state(monkeypatch, "virtual", written)
    h = _bare_hypnos(tmp_path / "desired.json", clock=None)
    h._suspend_perception()  # must not raise in non-playlist modes
    h._restore_perception()
    assert written == ["off", "virtual"]


def test_replay_crash_still_restores_clock_and_locus(tmp_path, monkeypatch):
    """The pipeline invokes restore from a finally; a mid-window replay crash
    must leave BOTH the clock resumed and the locus restored."""
    from kaine.modules.topos.feed import PlaylistClock

    written = []
    _stub_perception_state(monkeypatch, "virtual", written)

    clock = PlaylistClock(1, clock=_FakeClock())
    clock.start()
    h = _bare_hypnos(tmp_path / "desired.json", clock=clock)

    h._suspend_perception()
    assert clock.paused
    with pytest.raises(RuntimeError):
        try:
            raise RuntimeError("replay crashed mid-window")
        finally:
            h._restore_perception()
    assert not clock.paused
    assert written[-1] == "virtual"


def test_desired_state_file_contains_flags_only(tmp_path):
    """The write path is perception_state.write_desired_locus itself: the file
    carries only DesiredState flag keys — zero raw-sense-data persistence."""
    import json

    from kaine.perception_state import write_desired_locus

    p = tmp_path / "desired.json"
    write_desired_locus("off", path=p)
    data = json.loads(p.read_text())
    assert set(data) <= {
        "audio_live_desired",
        "video_live_desired",
        "locus",
        "locus_locked",
        "locked_by",
    }
