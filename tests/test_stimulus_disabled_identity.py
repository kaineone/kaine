# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Off equals absent: with stimulus control off the build behaves as one without it.

``GOLDEN`` is the digest of ``tests/stimulus_identity_harness.py`` run on the
build before stimulus control existed (origin/main d7fabdc0, after the playlist A/V sync): extract that
commit's ``kaine`` package to a directory, then from that directory run
``python -c "import sys, runpy; sys.path.insert(0, '.');
runpy.run_path('<worktree>/tests/stimulus_identity_harness.py', run_name='__main__')"``.

The harness drives the affect module, the action layer, the effectors module,
the welfare observer's records, the playlist video source and the real playlist
audio producer (paced by a manual shared clock, with a stall and a pause) with a script that
includes realized stimulus actions and a signed act intent naming the stimulus
effector. With the component off, every output is bit-identical.
"""
from __future__ import annotations

import pytest

from tests import stimulus_identity_harness as harness

GOLDEN = "8806003e8f337aae5d18cfb0cec1f53363fe75f368a7e27d304c889ad1a7fd49"


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
    reason, runtime = _stimulus_control_runtime(
        {
            "stimulus_control": {"enabled": True},
            "preservation": {"welfare_response": {"enabled": True}},
        },
        None,
        0,
    )
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


def test_the_boot_gives_stage_m_the_effectors_ready_check(tmp_path):
    pytest.importorskip("av")
    import time as _time

    from kaine.cycle.__main__ import _with_stimulus_act
    from kaine.cycle.boot_context import BootContext
    from kaine.modules.effectors.stimulus.config import StimulusControlConfig
    from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime
    from kaine.workspace.stimulus_policy import StimulusActSource
    from tests.stimulus_media import write_manifest

    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=_time.monotonic, seed=1
    )
    runtime.install_programme(
        str(write_manifest(tmp_path / "f", [("a.mkv", (255, 0, 0), 300.0, 0.3)])),
        start=False,
    )

    class _Effectors:
        enabled_effectors = frozenset({"stimulus"})

    class _Registry:
        entity_clock = None

        def __contains__(self, name):
            return name == "effectors"

        def get(self, name):
            return _Effectors()

    ctx = BootContext()
    ctx.stimulus_control = runtime
    ctx.registry = _Registry()
    ctx.staging_enabled = False
    wrapped = _with_stimulus_act(ctx, object())
    assert isinstance(wrapped, StimulusActSource)
    assert wrapped._ready == runtime.effector().ready
