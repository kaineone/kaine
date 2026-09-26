# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.research.ignition_study.overlay import build_overlay


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "echo",
        "soma",
        "chronos",
        "topos",
        "nous",
        "mnemos",
        "eidolon",
        "thymos",
        "praxis",
        "lingua",
        "vox",
        "audition",
        "hypnos",
        "empatheia",
        "phantasia",
        "perception",
        "mundus",
    ]
    monkeypatch.setattr("kaine.boot.known_module_names", lambda: names)
    return names


@pytest.fixture
def repo(tmp_path, known_modules):
    repo_root = tmp_path / "repo"
    cfg = repo_root / "config"
    cfg.mkdir(parents=True)
    (cfg / "profiles").mkdir()
    (cfg / "kaine.toml").write_text(
        '[modules]\n'
        'echo = false\n'
        'soma = false\n'
        '[topos]\n'
        'encoder_local_dir = "state/models"\n'
    )
    (cfg / "kaine.operator.toml").write_text(
        '[inference]\n'
        'server = "http://operator.local:8080"\n'
    )
    return repo_root


@pytest.fixture
def plan(repo):
    return {
        "study_id": "overlay-test",
        "repo_root": str(repo),
        "base_modules": ["soma", "chronos", "topos"],
        "order": ["thymos", "mnemos"],
        "programme": {"manifest": str(repo / "programme.toml"), "sha256": "a" * 64},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "main": 11, "control": 12},
        },
        "collections": {"gestation": "g_", "main": "m_", "control": "c_"},
        "viewings_per_line": 2,
    }


def test_overlay_gestation_modules(repo, plan):
    overlay, enabled, _ = build_overlay(
        plan, "gestation", "gestation", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled == {"soma", "chronos", "topos"}
    assert overlay["modules"]["soma"] is True
    assert overlay["modules"]["thymos"] is False
    assert overlay["modules"]["echo"] is False
    assert overlay["perception_feed"]["mode"] == "womb"
    assert "playlist_manifest" not in overlay["perception_feed"]


def test_overlay_main_modules_accumulate(repo, plan):
    overlay0, enabled0, _ = build_overlay(
        plan, "main", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled0 == {"soma", "chronos", "topos"}
    assert overlay0["perception_feed"]["mode"] == "playlist"
    assert overlay0["perception_feed"]["playlist_manifest"] == plan["programme"]["manifest"]

    overlay1, enabled1, _ = build_overlay(
        plan, "main", "viewing", 1, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled1 == {"soma", "chronos", "topos", "thymos"}
    assert overlay1["modules"]["thymos"] is True
    assert overlay1["modules"]["mnemos"] is False


def test_overlay_control_only_base(repo, plan):
    overlay, enabled, _ = build_overlay(
        plan, "control", "viewing", 1, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled == {"soma", "chronos", "topos"}
    assert overlay["modules"]["thymos"] is False


def test_overlay_isolation_keys(repo, plan):
    for line in ["gestation", "main", "control"]:
        overlay, _, _ = build_overlay(
            plan, line, "gestation" if line == "gestation" else "viewing",
            0, repo, repo / "config" / "kaine.toml",
            repo / "config" / "kaine.operator.toml",
        )
        assert overlay["mnemos"]["collection_prefix"] == plan["collections"][line]
        assert overlay["empatheia"]["collection"] == plan["collections"][line]


def test_overlay_operator_values_kept(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "main", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["inference"]["server"] == "http://operator.local:8080"


def test_overlay_phantasia_and_preservation(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "main", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["ignition_log"]["enabled"] is True
    assert overlay["research_event_log"]["enabled"] is True
    assert overlay["preservation"]["divergence_monitor"]["enabled"] is True
    assert overlay["preservation"]["welfare_response"]["enabled"] is True
    assert overlay["phantasia"]["training_enabled"] is True
    assert overlay["phantasia"]["persist_weights"] is True
    assert overlay["developmental_stage"]["enabled"] is True


def test_overlay_absolute_encoder_dir(repo, plan):
    overlay, _, models_dir = build_overlay(
        plan, "main", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    expected = str((repo / "state" / "models").resolve())
    assert overlay["topos"]["encoder_local_dir"] == expected
    assert models_dir == expected


def test_operator_encoder_dir_wins_and_is_made_absolute(tmp_path):
    from kaine.config import deep_merge
    from kaine.research.ignition_study.overlay import _absolute_encoder_dir

    base = {"topos": {"encoder_local_dir": "state/models/shipped"}}
    operator = {"topos": {"encoder_local_dir": "models/mine"}}
    got = _absolute_encoder_dir(tmp_path, deep_merge(base, operator))
    assert got == str((tmp_path / "models" / "mine").resolve())
