# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Off equals absent: with stimulus control off the build behaves as one without it.

``GOLDEN`` is the digest of ``tests/stimulus_identity_harness.py`` run on the
build before stimulus control existed (origin/main cb41895b): extract that
commit's ``kaine`` package to a directory, then from that directory run
``python -c "import sys, runpy; sys.path.insert(0, '.');
runpy.run_path('<worktree>/tests/stimulus_identity_harness.py', run_name='__main__')"``.

The harness drives the affect module, the action layer, the effectors module,
the welfare observer's records and the playlist video source with a script that
includes realized stimulus actions and a signed act intent naming the stimulus
effector. With the component off, every output is bit-identical.
"""
from __future__ import annotations

import pytest

from tests import stimulus_identity_harness as harness

GOLDEN = "dc0db1d7e4f51d83aec57901c6bd8f162fd63bcd6cb9920b776483415ba957f7"


async def test_off_is_bit_identical_to_the_build_without_it(tmp_path):
    pytest.importorskip("fakeredis.aioredis")
    result = await harness.run(tmp_path)
    assert harness.digest(result) == GOLDEN


async def test_the_harness_sees_the_component_when_it_is_on(tmp_path):
    pytest.importorskip("fakeredis.aioredis")
    result = await harness.run(tmp_path, affect_setup=lambda affect: affect.set_stimulus_credit())
    assert harness.digest(result) != GOLDEN


def test_absent_and_off_build_no_runtime():
    from kaine.cycle.__main__ import _stimulus_control_runtime

    assert _stimulus_control_runtime({}, None, 0) == (None, None)
    assert _stimulus_control_runtime({"stimulus_control": {"enabled": False}}, None, 0) == (None, None)
    reason, runtime = _stimulus_control_runtime({"stimulus_control": {"enabled": True}}, None, 0)
    assert reason is None and runtime is not None


def test_the_shipped_configuration_is_off():
    import tomllib
    from pathlib import Path

    from kaine.modules.effectors.stimulus.config import StimulusControlConfig

    shipped = tomllib.loads(Path("config/kaine.toml").read_text(encoding="utf-8"))
    config = StimulusControlConfig.from_section(shipped.get("stimulus_control"))
    assert config.enabled is False
    assert "stimulus" not in (shipped.get("effectors") or {}).get("enabled_effectors", [])
    # The shipped values are the design's provisional bounds.
    assert (config.min_interval_s, config.seeks_per_awake_hour, config.pause_max_s) == (30.0, 20, 120.0)
    assert (config.gain_step_db, config.gain_max_db, config.channels) == (2.0, 6.0, ())


def test_off_leaves_the_run_manifest_unchanged(tmp_path):
    from kaine.boot.perception_feed import gather_perception_feed_descriptor

    feed = {"mode": "playlist", "playlist_manifest": str(tmp_path / "missing.toml")}
    absent = gather_perception_feed_descriptor({"perception_feed": feed})
    off = gather_perception_feed_descriptor(
        {"perception_feed": feed, "stimulus_control": {"enabled": False}}
    )
    on = gather_perception_feed_descriptor(
        {"perception_feed": feed, "stimulus_control": {"enabled": True}}
    )
    assert absent == off
    assert "stimulus_control" not in off
    assert on["stimulus_control"]["enabled"] is True
    assert on["stimulus_control"]["gain_max_db"] == 6.0


def test_off_leaves_the_action_policy_unwrapped():
    from kaine.cycle.__main__ import _with_stimulus_act
    from kaine.cycle.boot_context import BootContext

    ctx = BootContext()
    policy = object()
    assert _with_stimulus_act(ctx, policy) is policy
