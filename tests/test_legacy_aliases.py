# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the runtime legacy alias readers in ``kaine.legacy_aliases``."""

import argparse
import copy
import logging

import pytest

from kaine import legacy_aliases, legacy_names


def _set_scope(monkeypatch, scope: str) -> None:
    """Mark one codemod scope as done for a single test."""
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, scope, "done")


def test_scope_done_initially_pending() -> None:
    assert not legacy_aliases.scope_done("keys")


def test_active_filters_by_scope(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    entries = (
        {"old": "a", "new": "b", "scope": "keys"},
        {"old": "c", "new": "d", "scope": "operator"},
    )
    assert legacy_aliases.active(entries) == [entries[0]]


def test_normalize_config_layer_is_inert_while_pending(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    layer = {"thymos": {"x": 1}, "modules": {"thymos": True}}
    result = legacy_aliases.normalize_config_layer(layer, "config.toml")
    assert result == layer
    assert result is layer
    assert caplog.records == []


def test_normalize_config_layer_with_keys_done(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")

    source = "operator.toml"
    layer = {
        "thymos": {"some_key": 1},
        "modules": {"thymos": True},
        "perception_feed": {"mode": "womb", "womb": {"x": 1}},
        "nexus": {"port": 1},
        "spot": {"enabled": False},
    }
    original = copy.deepcopy(layer)

    expected = {
        "affect": {"some_key": 1},
        "modules": {"affect": True},
        "perception_feed": {"mode": "stimulus_source", "stimulus_source": {"x": 1}},
        "dashboard": {"port": 1},
        "supervisor": {"enabled": False},
    }

    result = legacy_aliases.normalize_config_layer(layer, source)
    assert result == expected
    assert layer == original
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert source in record.message
    assert legacy_names.ALIAS_LAST_RELEASE in record.message


def test_normalize_config_layer_compound_table(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    layer = {"phantasia": {"world_model": {"y": 2}}}
    result = legacy_aliases.normalize_config_layer(layer, "compound.toml")
    assert result == {"world_model": {"backend": {"y": 2}}}
    assert len(caplog.records) == 1


def test_normalize_config_layer_study_table(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    layer = {"syneidesis": {"x": 1}}
    result = legacy_aliases.normalize_config_layer(layer, "study.toml")
    assert result == {"workspace": {"x": 1}}


def test_normalize_config_layer_key_alias(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    layer = {"gestation": {"womb_ready_retry_seconds": 3}}
    result = legacy_aliases.normalize_config_layer(layer, "key.toml")
    assert result == {"gestation": {"stimulus_source_ready_retry_seconds": 3}}


def test_normalize_config_layer_table_conflict(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        legacy_aliases.normalize_config_layer({"spot": {}, "supervisor": {}}, "conflict.toml")
    message = str(exc_info.value)
    assert "[spot]" in message
    assert "[supervisor]" in message


def test_normalize_config_layer_module_flag_conflict(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        legacy_aliases.normalize_config_layer(
            {"modules": {"thymos": True, "affect": True}}, "conflict.toml"
        )
    message = str(exc_info.value)
    assert "[modules].thymos" in message
    assert "[modules].affect" in message


def test_normalize_config_layer_module_flag_no_mutation(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    layer = {"modules": {"thymos": True}}
    original = copy.deepcopy(layer)
    result = legacy_aliases.normalize_config_layer(layer, "flag.toml")
    assert result == {"modules": {"affect": True}}
    assert layer == original


def test_normalize_config_layer_key_alias_no_mutation(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    layer = {"gestation": {"womb_ready_retry_seconds": 3}}
    original = copy.deepcopy(layer)
    result = legacy_aliases.normalize_config_layer(layer, "key.toml")
    assert result == {"gestation": {"stimulus_source_ready_retry_seconds": 3}}
    assert layer == original


def test_normalize_config_layer_value_replacement(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    _set_scope(monkeypatch, "persisted")
    layer = {"mnemos": {"collection_prefix": "mnemos_"}}
    original = copy.deepcopy(layer)
    result = legacy_aliases.normalize_config_layer(layer, "value.toml")
    assert result == {"episodic_memory": {"collection_prefix": "episodic_memory_"}}
    assert layer == original
    assert len(caplog.records) == 1
    assert '= "mnemos_" -> "episodic_memory_"' in caplog.records[0].message


def test_normalize_config_layer_no_changes_returns_same_object(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    layer = {"some_table": {"some_key": 1}}
    result = legacy_aliases.normalize_config_layer(layer, "none.toml")
    assert result is layer
    assert caplog.records == []


def test_normalize_config_layer_key_conflict(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    old_key = legacy_names.CONFIG_KEYS[0]["old"]
    new_key = legacy_names.CONFIG_KEYS[0]["new"]
    layer = {"gestation": {old_key: 1, new_key: 2}}
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        legacy_aliases.normalize_config_layer(layer, "conflict.toml")
    message = str(exc_info.value)
    assert old_key in message
    assert new_key in message


def test_getenv_is_inert_while_pending() -> None:
    env = {"KAINE_NEXUS_PORT": "8080"}
    assert legacy_aliases.getenv("KAINE_NEXUS_PORT", environ=env) == "8080"


def test_getenv_deprecation_warning_once(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "operator")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())
    env = {"KAINE_NEXUS_PORT": "8080"}

    assert legacy_aliases.getenv("KAINE_NEXUS_PORT", environ=env) == "8080"
    assert len(caplog.records) == 1
    assert "KAINE_DASHBOARD_PORT" in caplog.records[0].message

    caplog.clear()
    assert legacy_aliases.getenv("KAINE_NEXUS_PORT", environ=env) == "8080"
    assert caplog.records == []


def test_getenv_both_names_equal_no_warning(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "operator")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())
    env = {"KAINE_NEXUS_PORT": "8080", "KAINE_DASHBOARD_PORT": "8080"}
    assert legacy_aliases.getenv("KAINE_NEXUS_PORT", environ=env) == "8080"
    assert caplog.records == []


def test_getenv_both_names_different_raises(monkeypatch) -> None:
    _set_scope(monkeypatch, "operator")
    env = {
        "KAINE_NEXUS_PORT": "s3cret-a",
        "KAINE_DASHBOARD_PORT": "s3cret-b",
    }
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        legacy_aliases.getenv("KAINE_NEXUS_PORT", environ=env)
    message = str(exc_info.value)
    assert "KAINE_NEXUS_PORT" in message
    assert "KAINE_DASHBOARD_PORT" in message
    assert "s3cret-a" not in message
    assert "s3cret-b" not in message


def test_getenv_both_names_different_other_pair(monkeypatch) -> None:
    _set_scope(monkeypatch, "operator")
    env = {
        "KAINE_MUNDUS_OPERATOR_APPROVED": "1",
        "KAINE_EMBODIMENT_OPERATOR_APPROVED": "0",
    }
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        legacy_aliases.getenv("KAINE_MUNDUS_OPERATOR_APPROVED", environ=env)
    message = str(exc_info.value)
    assert "KAINE_MUNDUS_OPERATOR_APPROVED" in message
    assert "KAINE_EMBODIMENT_OPERATOR_APPROVED" in message
    assert "1" not in message
    assert "0" not in message


def test_getenv_unknown_name_passed_through(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "operator")
    env = {"KAINE_UNKNOWN": "x"}
    assert legacy_aliases.getenv("KAINE_UNKNOWN", environ=env) == "x"
    assert caplog.records == []


def test_add_cli_aliases_is_inert_while_pending() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve-dashboard", action="store_true")
    legacy_aliases.add_cli_aliases(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--serve-nexus"])


def test_add_cli_aliases_with_operator_done(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "operator")
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-development", type=int)
    parser.add_argument("--serve-dashboard", action="store_true")
    legacy_aliases.add_cli_aliases(parser)

    args = parser.parse_args(["--db-gestation", "7"])
    assert args.db_development == 7
    assert len(caplog.records) == 1
    assert "--db-gestation" in caplog.records[0].message

    caplog.clear()
    args = parser.parse_args(["--serve-nexus"])
    assert args.serve_dashboard is True
    assert len(caplog.records) == 1
    assert "--serve-nexus" in caplog.records[0].message

    help_text = parser.format_help()
    assert "--db-gestation" not in help_text
    assert "--serve-nexus" not in help_text


def test_add_cli_aliases_skips_missing_new_option(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "operator")
    parser = argparse.ArgumentParser()
    parser.add_argument("--other", action="store_true")
    legacy_aliases.add_cli_aliases(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--serve-nexus"])
    assert caplog.records == []


def test_resolve_seam_is_inert_while_pending() -> None:
    assert legacy_aliases.resolve_seam("soma.forward_model") == "soma.forward_model"


def test_resolve_seam_with_keys_done(caplog, monkeypatch) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    assert legacy_aliases.resolve_seam("soma.forward_model") == "interoception.forward_model"
    assert legacy_aliases.resolve_seam("oscillator.thymos") == "oscillator.affect"
    assert legacy_aliases.resolve_seam("workspace.broadcast") == "workspace.broadcast"
    assert len([r for r in caplog.records if "deprecated" in r.message]) == 2


def test_map_module_key_and_list(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    assert legacy_aliases.map_module_key("thymos") == "affect"
    assert legacy_aliases.map_module_list(["thymos", "audition"]) == ["affect", "audition"]


def test_map_module_key_is_inert_while_pending() -> None:
    assert legacy_aliases.map_module_key("thymos") == "thymos"


def test_map_module_keys(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    mapping = {"thymos": 1, "audition": 2}
    assert legacy_aliases.map_module_keys(mapping) == {"affect": 1, "audition": 2}

    both = {"thymos": 1, "affect": 2}
    result = legacy_aliases.map_module_keys(both)
    assert result == {"affect": 2}
    conflict_records = [r for r in caplog.records if "both old and new" in r.message]
    assert len(conflict_records) == 1


def test_map_module_keys_inert_while_pending() -> None:
    mapping = {"thymos": 1}
    assert legacy_aliases.map_module_keys(mapping) is mapping


def test_map_stream(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    assert legacy_aliases.map_stream("soma.report") == "interoception.report"
    assert legacy_aliases.map_stream("eidolon.self_model") == "self_model.document"
    assert legacy_aliases.map_stream("volition_feedback.out") == "action_selection_feedback.out"
    assert legacy_aliases.map_stream("workspace.broadcast") == "workspace.broadcast"


def test_map_record(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    record = {
        "event_type": "thymos.state",
        "source": "soma",
        "thymos_state": {},
        "chronos": 1,
        "other": 2,
    }
    expected = {
        "event_type": "affect.state",
        "source": "interoception",
        "affect_state": {},
        "sequence": 1,
        "other": 2,
    }
    result = legacy_aliases.map_record(record)
    assert result == expected
    assert record == {
        "event_type": "thymos.state",
        "source": "soma",
        "thymos_state": {},
        "chronos": 1,
        "other": 2,
    }


def test_map_record_is_inert_while_pending() -> None:
    record = {"event_type": "thymos.state", "source": "soma"}
    assert legacy_aliases.map_record(record) is record


def test_map_record_keeps_new_field_both_orders(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "keys")
    monkeypatch.setattr(legacy_aliases, "_record_warnings_seen", set())
    for record in (
        {"thymos_state": "old", "affect_state": "new"},
        {"affect_state": "new", "thymos_state": "old"},
    ):
        result = legacy_aliases.map_record(record)
        assert result == {"affect_state": "new"}
        assert "thymos_state" not in result
    assert len([r for r in caplog.records if "both present" in r.message]) == 1


def test_map_sidecar_dir(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    assert legacy_aliases.map_sidecar_dir("nous_policy") == "planning_policy"


def test_map_sidecar_dir_inert_while_pending() -> None:
    assert legacy_aliases.map_sidecar_dir("nous_policy") == "nous_policy"


def test_map_bundle_member(monkeypatch) -> None:
    _set_scope(monkeypatch, "keys")
    assert (
        legacy_aliases.map_bundle_member("gestation/gestation_progress.json")
        == "development/gestation_progress.json"
    )
    assert (
        legacy_aliases.map_bundle_member("phantasia/world_model.ckpt")
        == "world_model/world_model.ckpt"
    )


def test_map_bundle_member_is_inert_while_pending(monkeypatch) -> None:
    assert legacy_aliases.map_bundle_member("gestation/x") == "gestation/x"


def test_map_stage_record(monkeypatch) -> None:
    _set_scope(monkeypatch, "persisted")
    data = {"stage": "gestation", "gestation_started_at": "t", "womb_seed": 3}
    expected = {
        "stage": "development",
        "development_started_at": "t",
        "stimulus_source_seed": 3,
    }
    assert legacy_aliases.map_stage_record(data) == expected


def test_map_stage_record_is_inert_while_pending() -> None:
    data = {"stage": "gestation"}
    assert legacy_aliases.map_stage_record(data) is data


def test_map_stage_record_keeps_new_field_both_orders(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="kaine.legacy")
    _set_scope(monkeypatch, "persisted")
    monkeypatch.setattr(legacy_aliases, "_record_warnings_seen", set())
    for data in (
        {"gestation_started_at": "old", "development_started_at": "new"},
        {"development_started_at": "new", "gestation_started_at": "old"},
    ):
        result = legacy_aliases.map_stage_record(data)
        assert result == {"development_started_at": "new"}
        assert "gestation_started_at" not in result
    assert len([r for r in caplog.records if "both present" in r.message]) == 1


def test_map_stage_record_unhashable_stage_values(monkeypatch) -> None:
    _set_scope(monkeypatch, "persisted")
    assert legacy_aliases.map_stage_record({"stage": ["gestation"]}) == {"stage": ["gestation"]}
    assert legacy_aliases.map_stage_record({"stage": 3}) == {"stage": 3}


def test_lived_artifact_paths() -> None:
    paths = legacy_aliases.lived_artifact_paths()
    assert "hypnos/consolidation_divergence.json" in paths
    assert "sleep/consolidation_divergence.json" in paths
    assert len(paths) == len(set(paths))
