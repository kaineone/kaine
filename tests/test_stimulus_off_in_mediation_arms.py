# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The boot refuses stimulus control in a workspace-mediation arm, and a bad section.

The workspace-mediation arms compare processors on one shared programme, so an
entity-chosen stimulus would confound them; the boot refuses an arm whose merged
configuration enables stimulus control. An invalid section is refused too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.config import load_kaine_config, study_path
from kaine.cycle.__main__ import STIMULUS_CONTROL_REFUSED_EXIT, _stimulus_control_runtime
from kaine.modules.effectors.stimulus.config import StimulusControlConfig

_MEDIATION_ARMS = sorted(p.stem for p in Path("config/studies").glob("workspace_mediation_*.toml"))


def test_there_are_mediation_arms_to_guard():
    assert len(_MEDIATION_ARMS) >= 5
    assert STIMULUS_CONTROL_REFUSED_EXIT not in (0, 1, 2)


@pytest.mark.parametrize("study", _MEDIATION_ARMS)
def test_an_arm_that_enables_it_is_refused(study, tmp_path):
    operator = tmp_path / "operator.toml"
    operator.write_text("[stimulus_control]\nenabled = true\n", encoding="utf-8")
    config = load_kaine_config(
        "config/kaine.toml",
        operator,
        study=study,
        studies_dir=study_path(study).parent,
    )
    assert config["stimulus_control"]["enabled"] is True
    reason, runtime = _stimulus_control_runtime(config, study, 0)
    assert runtime is None
    assert reason is not None and "workspace-mediation" in reason


@pytest.mark.parametrize("study", _MEDIATION_ARMS)
def test_an_arm_with_it_off_boots_without_it(study):
    reason, runtime = _stimulus_control_runtime({"stimulus_control": {"enabled": False}}, study, 0)
    assert (reason, runtime) == (None, None)


def test_other_studies_may_enable_it():
    reason, runtime = _stimulus_control_runtime(
        {"stimulus_control": {"enabled": True}}, "development_run", 0
    )
    assert reason is None and runtime is not None


@pytest.mark.parametrize(
    "section",
    [
        {"enabled": True, "gain_max_db": 9.0},
        {"enabled": True, "stage": "learned"},
        {"enabled": True, "gain_step_db": 4.0, "gain_max_db": 2.0},
        {"enabled": True, "seeks_per_awake_hour": -1},
        {"enabled": True, "min_interval_s": 0},
        {"enabled": True, "pause_max_s": float("inf")},
        {"enabled": True, "channels": "other.toml"},
        {"enabled": "yes"},
        {"enabled": True, "brightness": 1},
    ],
)
def test_an_invalid_section_is_refused(section):
    with pytest.raises(ValueError):
        StimulusControlConfig.from_section(section)
    reason, runtime = _stimulus_control_runtime({"stimulus_control": section}, None, 0)
    assert runtime is None and reason.startswith("invalid [stimulus_control]")


def test_declared_actions_add_channels_only_from_two():
    one = StimulusControlConfig.from_section({"enabled": True})
    two = StimulusControlConfig.from_section({"enabled": True, "channels": ["b.toml"]})
    assert one.declared_actions() == ("pause", "resume", "next", "previous", "louder", "quieter")
    assert two.declared_actions()[-2:] == ("channel:0", "channel:1")
