# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace arm configuration tests."""
from __future__ import annotations

import types
from pathlib import Path

import pytest

import kaine.cycle.__main__ as cyc
from kaine.boot import make_salience_factors
from kaine.config import (
    SHIPPED_CONFIG_PATH,
    ProfileError,
    deep_merge,
    load_kaine_config,
    load_runtime_config,
)
from kaine.cycle.affect_state import AffectStateProvider
from kaine.cycle.boot_context import BootContext
from kaine.modules.registry import ModuleRegistry
from kaine.research.ignition_study.overlay import build_overlay

_MISSING = "/nonexistent-operator-for-tests.toml"
_REPO = Path(__file__).resolve().parents[1]


def test_shipped_arm_is_competitive():
    cfg = load_kaine_config(profile="thesis_test", operator_path=_MISSING)
    assert cfg["syneidesis"]["arm"] == "competitive"


def test_arm_kwargs_default_and_seed():
    assert cyc._syneidesis_arm_kwargs({}, types.SimpleNamespace(seed=42)) == {
        "arm": "competitive",
        "arm_seed": 42,
    }
    assert cyc._syneidesis_arm_kwargs(
        {"arm": " Matched "}, types.SimpleNamespace(seed=7)
    ) == {"arm": "matched", "arm_seed": 7}
    assert cyc._syneidesis_arm_kwargs({"arm": "pooled"}, None) == {
        "arm": "pooled",
        "arm_seed": None,
    }


def test_shipped_config_passes_the_syneidesis_key_guard():
    make_salience_factors(
        load_kaine_config(profile="thesis_test", operator_path=_MISSING),
        AffectStateProvider(),
    )


def test_each_arm_passes_the_syneidesis_key_guard():
    for arm in ("competitive", "matched", "pooled"):
        make_salience_factors(
            {"syneidesis": {"arm": arm}}, AffectStateProvider()
        )


def test_study_overlay_passes_the_syneidesis_key_guard(monkeypatch, tmp_path):
    plan = {
        "study_id": "s",
        "repo_root": str(_REPO),
        "base_modules": ["soma"],
        "order": ["mnemos"],
        "programme": {
            "manifest": str(tmp_path / "p.toml"),
            "sha256": "a" * 64,
        },
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "g_",
            "branch": "b_",
            "repeat": "r_",
            "accumulate": "a_",
        },
    }
    overlay, _, _ = build_overlay(
        plan,
        "branch",
        "viewing",
        1,
        _REPO,
        _REPO / "config" / "kaine.toml",
        tmp_path / "missing-operator.toml",
    )
    make_salience_factors(
        deep_merge(
            load_kaine_config(profile="thesis_test", operator_path=_MISSING),
            overlay,
        ),
        AffectStateProvider(),
    )


@pytest.mark.asyncio
async def test_boot_path_builds_the_workspace_for_every_study(monkeypatch):
    monkeypatch.chdir(_REPO)
    for study in (
        None,
        "workspace_mediation_competitive",
        "workspace_mediation_matched",
        "workspace_mediation_pooled",
    ):
        cfg = load_runtime_config(
            SHIPPED_CONFIG_PATH,
            _MISSING,
            study=study,
            env={},
        )
        ctx = BootContext(
            kaine_config=cfg,
            registry=ModuleRegistry(),
            run_ctx=types.SimpleNamespace(seed=3),
        )
        assert await cyc._phase_workspace(ctx) is None
        expected = (
            "competitive"
            if study is None
            else study.removeprefix("workspace_mediation_")
        )
        assert ctx.syneidesis.arm == expected
        assert cfg["lingua"]["temperature"] == (0.7 if study is None else 0.0)


def test_study_may_not_change_modules(tmp_path):
    (tmp_path / "bad.toml").write_text("[modules]\nmnemos = true\n")
    with pytest.raises(ProfileError):
        load_kaine_config(operator_path=_MISSING, study="bad", studies_dir=tmp_path)
    with pytest.raises(ProfileError):
        load_kaine_config(
            operator_path=_MISSING, study="missing", studies_dir=tmp_path
        )
    with pytest.raises(ProfileError):
        load_kaine_config(
            operator_path=_MISSING, study="BAD/../x", studies_dir=tmp_path
        )


def test_study_file_allowlist(tmp_path):
    for body in (
        "[preservation]\nenabled = false\n",
        "[oscillator]\nenabled = true\n",
    ):
        table = body[1:].split("]")[0]
        (tmp_path / "bad2.toml").write_text(body)
        with pytest.raises(ProfileError) as exc_info:
            load_kaine_config(operator_path=_MISSING, study="bad2", studies_dir=tmp_path)
        assert table in str(exc_info.value)

    (tmp_path / "ok.toml").write_text(
        "[lingua]\ntemperature = 0.0\n"
        "[syneidesis]\narm = \"pooled\"\n"
        "[experiment]\nseed = 5\n"
        "[individuation]\nprobe_temperature = 0.0\n"
    )
    cfg = load_kaine_config(operator_path=_MISSING, study="ok", studies_dir=tmp_path)
    assert cfg["experiment"]["seed"] == 5


def test_study_wins_over_operator(tmp_path):
    (tmp_path / "op.toml").write_text(
        '[lingua]\ntemperature = 0.9\n[syneidesis]\narm = "competitive"\n'
    )
    cfg = load_kaine_config(
        operator_path=tmp_path / "op.toml",
        study="workspace_mediation_pooled",
        studies_dir=_REPO / "config" / "studies",
    )
    assert cfg["lingua"]["temperature"] == 0.0
    assert cfg["syneidesis"]["arm"] == "pooled"


def test_study_resolved_from_environment():
    cfg = load_runtime_config(
        _REPO / "config" / "kaine.toml",
        _MISSING,
        env={"KAINE_STUDY": "workspace_mediation_matched"},
        profiles_dir=_REPO / "config" / "profiles",
        studies_dir=_REPO / "config" / "studies",
    )
    assert cfg["syneidesis"]["arm"] == "matched"
