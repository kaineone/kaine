# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.evaluation.config import EvaluationConfig, load_evaluation_config


def test_defaults_enable_everything():
    c = EvaluationConfig()
    assert c.enabled is True
    assert c.workspace_trajectory is True
    assert c.ab_divergence is True
    assert c.ab_sample_rate == 1.0
    assert c.voice_tracking is True
    assert c.module_attribution is True
    assert c.memory_probes is True
    assert c.proactive_audit is True
    assert c.eidolon_accuracy is True
    assert c.sleep_snapshots is True
    assert c.paths.retention_days == 30


def test_from_mapping_overrides():
    c = EvaluationConfig.from_mapping(
        {
            "enabled": False,
            "ab_sample_rate": 0.1,
            "paths": {"retention_days": 7, "trajectory_dir": "/tmp/x"},
        }
    )
    assert c.enabled is False
    assert c.ab_sample_rate == 0.1
    assert c.paths.retention_days == 7
    assert c.paths.trajectory_dir == "/tmp/x"


def test_load_from_kaine_toml(tmp_path):
    cfg_file = tmp_path / "kaine.toml"
    cfg_file.write_text(
        """
        [evaluation]
        enabled = true
        ab_sample_rate = 0.5

        [evaluation.paths]
        retention_days = 14
        """
    )
    c = load_evaluation_config(cfg_file)
    assert c.enabled is True
    assert c.ab_sample_rate == 0.5
    assert c.paths.retention_days == 14


def test_load_missing_file_returns_defaults(tmp_path):
    c = load_evaluation_config(tmp_path / "nope.toml")
    assert c == EvaluationConfig()


def test_shipped_kaine_toml_has_evaluation_block():
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "kaine.toml"
    c = load_evaluation_config(config_path)
    assert c.enabled is True
    assert c.paths.trajectory_dir == "data/workspace_trajectory"


# --- A/B baseline parity with the language organ -----------------------------
# The A/B-divergence baseline runs bare (no architecture). It MUST use the SAME
# model as Lingua, or the divergence measures a model difference instead of the
# architecture's conditioning. The baseline therefore DERIVES from lingua and
# fails closed on an explicit divergent value.


def test_eval_baseline_derives_from_lingua_when_unset():
    c = EvaluationConfig.from_mapping({}, lingua_model_id="some-org/some-model:99b")
    assert c.chat_model_id == "some-org/some-model:99b"


def test_eval_baseline_derives_via_loader_no_file(tmp_path):
    c = load_evaluation_config(
        tmp_path / "nope.toml", lingua_model_id="some-org/some-model:99b"
    )
    assert c.chat_model_id == "some-org/some-model:99b"


def test_eval_baseline_explicit_match_ok():
    c = EvaluationConfig.from_mapping(
        {"chat_model_id": "X:1"}, lingua_model_id="X:1"
    )
    assert c.chat_model_id == "X:1"


def test_eval_baseline_explicit_mismatch_fails_closed():
    with pytest.raises(ValueError, match="must equal"):
        EvaluationConfig.from_mapping(
            {"chat_model_id": "stock:latest"}, lingua_model_id="abliterated:9b"
        )


def test_shipped_config_omits_eval_model_so_it_derives(tmp_path):
    # The committed config must NOT pin its own eval model — it derives from
    # whatever organ the operator runs, so the two can never silently diverge.
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "kaine.toml"
    c = load_evaluation_config(config_path, lingua_model_id="operators-bigger:27b")
    assert c.chat_model_id == "operators-bigger:27b"


def test_shipped_lingua_organ_is_abliterated():
    # Guard against regressing the shipped organ to a stock, refusal-conditioned
    # model — abliteration is core to the sovereignty thesis (ABLITERATION.md).
    import tomllib
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "kaine.toml"
    raw = tomllib.loads(config_path.read_text())
    assert "abliterat" in raw["lingua"]["model_id"].lower()
    # And the eval block must not pin its own chat_model_id (it derives).
    assert "chat_model_id" not in (raw.get("evaluation") or {})


# --- WelfareConfig -----------------------------------------------------------


def test_welfare_config_defaults():
    from kaine.evaluation.config import WelfareConfig

    cfg = WelfareConfig()
    assert cfg.interoceptive_distress_threshold == pytest.approx(0.8)
    assert cfg.interoceptive_distress_duration_s == pytest.approx(30.0)


def test_welfare_config_from_mapping_override():
    from kaine.evaluation.config import WelfareConfig

    cfg = WelfareConfig.from_mapping(
        {"interoceptive_distress_threshold": 0.6, "interoceptive_distress_duration_s": 15.0}
    )
    assert cfg.interoceptive_distress_threshold == pytest.approx(0.6)
    assert cfg.interoceptive_distress_duration_s == pytest.approx(15.0)


def test_welfare_config_from_mapping_empty_uses_defaults():
    from kaine.evaluation.config import WelfareConfig

    cfg = WelfareConfig.from_mapping(None)
    assert cfg.interoceptive_distress_threshold == pytest.approx(0.8)
    assert cfg.interoceptive_distress_duration_s == pytest.approx(30.0)


def test_welfare_config_validation_rejects_negative_threshold():
    from kaine.evaluation.config import WelfareConfig

    with pytest.raises(ValueError, match="non-negative"):
        WelfareConfig(interoceptive_distress_threshold=-0.1)


def test_welfare_config_validation_rejects_zero_duration():
    from kaine.evaluation.config import WelfareConfig

    with pytest.raises(ValueError, match="positive"):
        WelfareConfig(interoceptive_distress_duration_s=0.0)


def test_evaluation_config_threads_welfare_config():
    """EvaluationConfig.from_mapping passes [evaluation.welfare] through."""
    from kaine.evaluation.config import EvaluationConfig

    cfg = EvaluationConfig.from_mapping(
        {"welfare": {"interoceptive_distress_threshold": 0.65}}
    )
    assert cfg.welfare.interoceptive_distress_threshold == pytest.approx(0.65)
    # Other keys stay at defaults.
    assert cfg.welfare.interoceptive_distress_duration_s == pytest.approx(30.0)


# --- operator-override merge in the loaders (#5) + chat_api_key derivation -----

def test_loaders_apply_operator_override(tmp_path):
    """The eval + research-log loaders must deep-merge the operator override so
    SSD-redirected paths set only in config/kaine.operator.toml take effect."""
    from kaine.evaluation.config import load_research_event_log_config

    shipped = tmp_path / "kaine.toml"
    shipped.write_text(
        "[evaluation]\nenabled = true\n\n"
        '[evaluation.paths]\ntrajectory_dir = "data/wt"\n\n'
        '[research_event_log]\nenabled = true\nlog_dir = "data/re"\n'
    )
    operator = tmp_path / "kaine.operator.toml"
    operator.write_text(
        '[evaluation.paths]\ntrajectory_dir = "/ssd/wt"\n\n'
        '[research_event_log]\nlog_dir = "/ssd/re"\n'
    )
    ev = load_evaluation_config(path=shipped, operator_path=operator)
    assert ev.paths.trajectory_dir == "/ssd/wt"
    rl = load_research_event_log_config(path=shipped, operator_path=operator)
    assert rl.log_dir == "/ssd/re"


def test_loaders_without_override_use_shipped(tmp_path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text('[evaluation.paths]\ntrajectory_dir = "data/wt"\n')
    ev = load_evaluation_config(path=shipped, operator_path=tmp_path / "absent.toml")
    assert ev.paths.trajectory_dir == "data/wt"


def test_chat_api_key_derives_from_lingua_and_explicit_overrides():
    assert EvaluationConfig.from_mapping({}, lingua_api_key="sk-organ").chat_api_key == "sk-organ"
    assert (
        EvaluationConfig.from_mapping(
            {"chat_api_key": "sk-eval"}, lingua_api_key="sk-organ"
        ).chat_api_key
        == "sk-eval"
    )
    assert EvaluationConfig.from_mapping({}).chat_api_key is None
