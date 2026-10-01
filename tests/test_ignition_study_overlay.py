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
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {"gestation": "g_", "branch": "b_", "repeat": "r_", "accumulate": "a_"},
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


def test_overlay_branch_modules_accumulate(repo, plan):
    overlay0, enabled0, _ = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled0 == {"soma", "chronos", "topos"}
    assert overlay0["perception_feed"]["mode"] == "playlist"
    assert overlay0["perception_feed"]["playlist_manifest"] == plan["programme"]["manifest"]

    overlay1, enabled1, _ = build_overlay(
        plan, "branch", "viewing", 1, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled1 == {"soma", "chronos", "topos", "thymos"}
    assert overlay1["modules"]["thymos"] is True
    assert overlay1["modules"]["mnemos"] is False

    overlay2, enabled2, _ = build_overlay(
        plan, "accumulate", "viewing", 2, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert enabled2 == {"soma", "chronos", "topos", "thymos", "mnemos"}


def test_overlay_repeat_only_base(repo, plan):
    for k in (0, 1, 2):
        overlay, enabled, _ = build_overlay(
            plan, "repeat", "viewing", k, repo, repo / "config" / "kaine.toml",
            repo / "config" / "kaine.operator.toml",
        )
        assert enabled == {"soma", "chronos", "topos"}
        assert overlay["modules"]["thymos"] is False
        assert overlay["modules"]["mnemos"] is False


def test_overlay_isolation_keys(repo, plan):
    for line in ["gestation", "branch", "repeat", "accumulate"]:
        overlay, _, _ = build_overlay(
            plan, line, "gestation" if line == "gestation" else "viewing",
            0, repo, repo / "config" / "kaine.toml",
            repo / "config" / "kaine.operator.toml",
        )
        expected = plan["collections"][line]
        if line == "branch":
            expected = f"{expected}0_"
        assert overlay["mnemos"]["collection_prefix"] == expected
        assert overlay["empatheia"]["collection"] == expected


def test_overlay_branch_collection_prefix_includes_k(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "branch", "viewing", 1, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["mnemos"]["collection_prefix"] == "b_1_"
    assert overlay["empatheia"]["collection"] == "b_1_"


def test_overlay_operator_values_kept(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["inference"]["server"] == "http://operator.local:8080"


def test_overlay_phantasia_and_preservation(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["ignition_log"]["enabled"] is True
    assert overlay["ignition_log"]["directory"] == "data/ignition"
    assert overlay["research_event_log"]["enabled"] is True
    assert overlay["preservation"]["divergence_monitor"]["enabled"] is True
    assert overlay["preservation"]["welfare_response"]["enabled"] is True
    assert overlay["phantasia"]["training_enabled"] is True
    assert overlay["phantasia"]["persist_weights"] is True
    assert overlay["developmental_stage"]["enabled"] is True
    assert overlay["developmental_stage"]["require_operator_ack_for_birth"] is False


def test_models_dir_honours_exported_environment(repo, plan, monkeypatch, tmp_path):
    shared = tmp_path / "shared-models"
    monkeypatch.setenv("KAINE_MODELS_DIR", str(shared))
    _, _, models_dir = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert models_dir == str(shared.resolve())


def test_models_dir_blank_environment_falls_back_to_repo(repo, plan, monkeypatch):
    monkeypatch.setenv("KAINE_MODELS_DIR", "  ")
    _, _, models_dir = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert models_dir == str((repo / "state" / "models").resolve())


def test_overlay_absolute_encoder_dir(repo, plan, monkeypatch):
    monkeypatch.delenv("KAINE_MODELS_DIR", raising=False)
    overlay, _, models_dir = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
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


def test_overlay_self_rhythm_enabled_gestation(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "gestation", "gestation", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["soma"]["self_rhythm_enabled"] is True


def test_overlay_self_rhythm_enabled_branch_viewing(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "branch", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["soma"]["self_rhythm_enabled"] is True


def test_overlay_self_rhythm_enabled_repeat_viewing(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "repeat", "viewing", 0, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["soma"]["self_rhythm_enabled"] is True


def test_overlay_self_rhythm_enabled_accumulate_viewing(repo, plan):
    overlay, _, _ = build_overlay(
        plan, "accumulate", "viewing", 1, repo, repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay["soma"]["self_rhythm_enabled"] is True


def test_overlay_self_rhythm_overrides_operator_false(repo, plan):
    op = repo / "config" / "kaine.operator.toml"
    op.write_text(
        "[soma]\n"
        "self_rhythm_enabled = false\n"
        "[developmental_stage]\n"
        "require_operator_ack_for_birth = true\n"
    )
    for line, kind, k in [
        ("gestation", "gestation", 0),
        ("branch", "viewing", 0),
        ("branch", "viewing", 2),
        ("repeat", "viewing", 0),
        ("accumulate", "viewing", 1),
    ]:
        overlay, _, _ = build_overlay(
            plan, line, kind, k, repo, repo / "config" / "kaine.toml", op,
        )
        # Study settings win over the operator's own file on every step.
        assert overlay["soma"]["self_rhythm_enabled"] is True
        assert overlay["developmental_stage"]["require_operator_ack_for_birth"] is False


_RECORDING_STEPS = [
    ("gestation", "gestation", 0),
    ("branch", "viewing", 1),
    ("accumulate", "viewing", 2),
]


def test_overlay_records_nexus_and_external_utterances_every_step(repo, plan):
    for line, kind, k in _RECORDING_STEPS:
        overlay, _, _ = build_overlay(
            plan, line, kind, k, repo, repo / "config" / "kaine.toml",
            repo / "config" / "kaine.operator.toml",
        )
        log = overlay["research_event_log"]
        assert log["enabled"] is True
        assert log["external_utterances"]["enabled"] is True
        assert log["nexus_record"]["enabled"] is True
        assert overlay["evaluation"]["workspace_trajectory"] is True
        assert overlay["ignition_log"]["enabled"] is True


def test_overlay_never_enables_raw_archive(repo, plan):
    op = repo / "config" / "kaine.operator.toml"
    op.write_text("[research_event_log.raw_archive]\nenabled = true\n")
    for line, kind, k in _RECORDING_STEPS:
        overlay, _, _ = build_overlay(
            plan, line, kind, k, repo, repo / "config" / "kaine.toml", op,
        )
        assert overlay["research_event_log"]["raw_archive"]["enabled"] is False


@pytest.fixture
def nine_plan(repo):
    order = [
        "mnemos",
        "phantasia",
        "nous",
        "eidolon",
        "empatheia",
        "vox",
        "praxis",
        "perception",
        "mundus",
    ]
    return {
        "study_id": "overlay-nine",
        "repo_root": str(repo),
        "base_modules": ["soma", "chronos", "topos"],
        "order": order,
        "programme": {"manifest": str(repo / "programme.toml"), "sha256": "a" * 64},
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


def test_overlay_voice_alignment_only_registered_step(nine_plan, repo):
    op = repo / "config" / "kaine.operator.voice.toml"
    op.write_text(
        "[hypnos.voice_alignment]\n"
        "enabled = true\n"
        'trainer_backend = "operator_backend"\n'
    )
    k_max = len(nine_plan["order"])
    sequence = [
        ("gestation", "gestation", 0),
        ("branch", "viewing", 0),
        ("repeat", "viewing", 0),
    ]
    for i in range(1, k_max + 1):
        sequence.append(("branch", "viewing", i))
        sequence.append(("accumulate", "viewing", i))

    for line, kind, k in sequence:
        overlay, _, _ = build_overlay(
            nine_plan,
            line,
            kind,
            k,
            repo,
            repo / "config" / "kaine.toml",
            op,
        )
        va = overlay["hypnos"]["voice_alignment"]
        if line == "accumulate" and k == k_max:
            assert va["enabled"] is True
            assert va["trainer_backend"] == "job_queue"
            assert va["hot_swap_mode"] == "organ_adapter"
        else:
            assert va["enabled"] is False
            assert va["trainer_backend"] == "operator_backend"
