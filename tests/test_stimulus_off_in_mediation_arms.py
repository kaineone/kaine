# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The boot refuses stimulus control in a between-arm study, without the welfare
net, and with a bad section.

The workspace-mediation and workspace-feedback arms compare processors on one
shared programme, so an entity-chosen stimulus would confound them; the boot
refuses an arm whose merged configuration enables stimulus control. Stimulus
control changes what the entity experiences, so it also needs the welfare
response on. An invalid section is refused too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.config import load_kaine_config, study_path
from kaine.cycle.__main__ import STIMULUS_CONTROL_REFUSED_EXIT, _stimulus_control_runtime
from kaine.modules.effectors.stimulus.config import StimulusControlConfig

_MEDIATION_ARMS = sorted(
    p.stem
    for pattern in ("workspace_mediation_*.toml", "workspace_feedback_*.toml")
    for p in Path("config/studies").glob(pattern)
)
_WELFARE_ON = {"preservation": {"welfare_response": {"enabled": True}}}


def _on(section=None):
    return {"stimulus_control": {"enabled": True, **(section or {})}, **_WELFARE_ON}


def test_there_are_mediation_arms_to_guard():
    assert len([a for a in _MEDIATION_ARMS if a.startswith("workspace_mediation")]) >= 5
    assert len([a for a in _MEDIATION_ARMS if a.startswith("workspace_feedback")]) >= 3
    assert STIMULUS_CONTROL_REFUSED_EXIT not in (0, 1, 2)


@pytest.mark.parametrize("study", _MEDIATION_ARMS)
def test_an_arm_that_enables_it_is_refused(study, tmp_path):
    operator = tmp_path / "operator.toml"
    operator.write_text(
        "[stimulus_control]\nenabled = true\n[preservation.welfare_response]\nenabled = true\n",
        encoding="utf-8",
    )
    config = load_kaine_config(
        "config/kaine.toml",
        operator,
        study=study,
        studies_dir=study_path(study).parent,
    )
    assert config["stimulus_control"]["enabled"] is True
    reason, runtime = _stimulus_control_runtime(config, study, 0)
    assert runtime is None
    assert reason is not None and "between-arm" in reason


@pytest.mark.parametrize("study", _MEDIATION_ARMS)
def test_an_arm_with_it_off_boots_without_it(study):
    reason, runtime = _stimulus_control_runtime({"stimulus_control": {"enabled": False}}, study, 0)
    assert (reason, runtime) == (None, None)


def test_other_studies_may_enable_it():
    reason, runtime = _stimulus_control_runtime(_on(), "development_run", 0)
    assert reason is None and runtime is not None


@pytest.mark.parametrize(
    "preservation",
    [{}, {"welfare_response": {"enabled": False}}],
)
def test_it_is_refused_without_the_welfare_response(preservation):
    reason, runtime = _stimulus_control_runtime(
        {"stimulus_control": {"enabled": True}, "preservation": preservation}, None, 0
    )
    assert runtime is None
    assert reason is not None and "welfare_response" in reason


def test_the_shipped_configuration_with_it_enabled_is_refused(tmp_path):
    operator = tmp_path / "operator.toml"
    operator.write_text("[stimulus_control]\nenabled = true\n", encoding="utf-8")
    config = load_kaine_config("config/kaine.toml", operator)
    reason, runtime = _stimulus_control_runtime(config, None, 0)
    assert runtime is None and "welfare_response" in reason


def test_the_boot_returns_the_refusal_exit_code_without_the_welfare_response(monkeypatch):
    import asyncio

    from kaine.cycle import __main__ as cyc
    from kaine.cycle.boot_context import BootContext

    ctx = BootContext()
    ctx.kaine_config = {"stimulus_control": {"enabled": True}}
    ctx.eval_cfg = type("E", (), {"chat_model_id": None})()
    monkeypatch.setattr(cyc, "planned_test_gate", lambda *a: (None, None, None), raising=False)
    monkeypatch.setattr(
        "kaine.experiment.planned_test_settings.planned_test_gate", lambda *a: (None, None, None)
    )
    exit_code = asyncio.run(cyc._phase_run_identity(ctx))
    assert exit_code == STIMULUS_CONTROL_REFUSED_EXIT


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
        {"enabled": True, "pause_share_max": 0.3},
        {"enabled": True, "pause_share_max": 0.02},
    ],
)
def test_an_invalid_section_is_refused(section):
    with pytest.raises(ValueError):
        StimulusControlConfig.from_section(section)
    reason, runtime = _stimulus_control_runtime(
        {"stimulus_control": section, **_WELFARE_ON}, None, 0
    )
    assert runtime is None and reason.startswith("invalid [stimulus_control]")


def test_declared_actions_add_channels_only_from_two():
    one = StimulusControlConfig.from_section({"enabled": True})
    two = StimulusControlConfig.from_section({"enabled": True, "channels": ["b.toml"]})
    assert one.declared_actions() == ("pause", "resume", "next", "previous", "louder", "quieter")
    assert two.declared_actions()[-2:] == ("channel:0", "channel:1")
