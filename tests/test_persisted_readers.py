# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the persisted-scope legacy alias readers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from kaine import legacy_aliases, legacy_names
from kaine.cycle.preservation_monitor import _map_arms
from kaine.legacy_aliases import (
    map_collection_prefix,
    map_freeze_source,
    map_stored_value,
    normalize_config_layer,
)
from kaine.lifecycle import maturation_ack
from kaine.modules.world_model.backend import (
    CheckpointMismatchError,
    _decode_checkpoint,
    _encode_checkpoint,
    _rssm_config_header,
)
from kaine.perception_state import read_desired, write_desired_locus
from kaine.research.ignition_study.runner import StudyRunner

OLD_DEVELOPMENT = next(e["old"] for e in legacy_names.STAGE_VALUES if e["new"] == "development")
OLD_MATURATION_TAG = next(e["old"] for e in legacy_names.STORED_TAGS if e["new"] == "maturation")

_OLD_COLLECTION_ENTRY = next(iter(legacy_aliases.active(legacy_names.COLLECTIONS)))
OLD_COLLECTION_PREFIX = _OLD_COLLECTION_ENTRY["old"]
NEW_COLLECTION_PREFIX = _OLD_COLLECTION_ENTRY["new"]

OLD_RECORD_FIELD = next(
    e["old"] for e in legacy_names.STAGE_FIELDS if e["new"] == "development_started_at"
)
OLD_MATURATION_BLOOM_FIELD = next(
    e["old"] for e in legacy_names.STAGE_FIELDS if e["new"] == "maturation_bloom_ends_at"
)

OLD_SELF_MODEL_KEY = next(
    k for k, e in legacy_names.MODULES.items() if e["new_key"] == "self_model"
)
OLD_SLEEP_KEY = next(
    k for k, e in legacy_names.MODULES.items() if e["new_key"] == "sleep"
)

OLD_WORLD_MODEL_FORMAT = next(
    e["old"] for e in legacy_names.STORED_TAGS if e["new"] == "kaine-world-model-rssm-npz-v1"
)
OLD_ENCODER_VERSION = next(
    e["old"] for e in legacy_names.STORED_TAGS if e["new"] == "world-model-encoder-v1"
)
NEW_WORLD_MODEL_FORMAT = next(
    e["new"] for e in legacy_names.STORED_TAGS if e["old"] == OLD_WORLD_MODEL_FORMAT
)
NEW_ENCODER_VERSION = next(
    e["new"] for e in legacy_names.STORED_TAGS if e["old"] == OLD_ENCODER_VERSION
)

OLD_SELF_MODEL_DRIFT = next(
    e["old"] for e in legacy_names.STORED_TAGS if e["new"] == "self_model_drift"
)


@pytest.fixture(autouse=True)
def _persisted_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")


@pytest.fixture
def desired_path(tmp_path: Path) -> Path:
    return tmp_path / "desired.json"


def test_map_stored_value_active_entries() -> None:
    for entry in legacy_aliases.active(legacy_names.STAGE_VALUES):
        assert map_stored_value(entry["old"]) == entry["new"]
    for entry in legacy_aliases.active(legacy_names.STORED_TAGS):
        assert map_stored_value(entry["old"]) == entry["new"]
    assert map_stored_value("unknown_string") == "unknown_string"
    assert map_stored_value(12345) == 12345
    # Only a string maps; a list holding an old value is returned as it is.
    old_value = legacy_names.STAGE_VALUES[0]["old"]
    assert map_stored_value([old_value]) == [old_value]


def test_map_stored_value_identity_while_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    for entry in legacy_aliases.active(legacy_names.STAGE_VALUES):
        assert map_stored_value(entry["old"]) == entry["old"]
    for entry in legacy_aliases.active(legacy_names.STORED_TAGS):
        assert map_stored_value(entry["old"]) == entry["old"]


def test_map_collection_prefix() -> None:
    assert map_collection_prefix(OLD_COLLECTION_PREFIX) == NEW_COLLECTION_PREFIX
    assert map_collection_prefix("my_custom_prefix") == "my_custom_prefix"


def test_map_collection_prefix_identity_while_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    assert map_collection_prefix(OLD_COLLECTION_PREFIX) == OLD_COLLECTION_PREFIX


def test_map_freeze_source_old_developmental() -> None:
    assert map_freeze_source(OLD_DEVELOPMENT) == "development"
    assert map_freeze_source("something_unmapped") == "something_unmapped"


def test_normalize_config_layer_rewrites_state_dirs() -> None:
    layer = {
        "self_model": {
            "persistence_path": f"state/{OLD_SELF_MODEL_KEY}/self_model.json",
        },
    }
    result = normalize_config_layer(layer, "test")
    assert (
        result["self_model"]["persistence_path"] == "state/self_model/self_model.json"
    )

    layer = {
        "sleep": {
            "voice_alignment": {
                "adapter_output_dir": f"state/{OLD_SLEEP_KEY}/adapters",
            },
        },
    }
    result = normalize_config_layer(layer, "test")
    assert (
        result["sleep"]["voice_alignment"]["adapter_output_dir"]
        == "state/sleep/adapters"
    )


def test_normalize_config_layer_leaves_other_paths() -> None:
    layer = {
        "a": {
            "already_new": "state/sleep/adapters",
            "data": "data/x",
            "absolute": f"/abs/state/{OLD_SELF_MODEL_KEY}/x",
        },
    }
    assert normalize_config_layer(layer, "test") == layer


def test_normalize_config_layer_identity_while_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    layer = {
        "self_model": {
            "persistence_path": f"state/{OLD_SELF_MODEL_KEY}/self_model.json",
        },
    }
    assert normalize_config_layer(layer, "test") == layer


def test_perception_state_old_development_lock(desired_path: Path) -> None:
    write_desired_locus(
        "virtual", locked=True, locked_by=OLD_DEVELOPMENT, path=desired_path
    )
    state = read_desired(desired_path)
    assert state.locus == "virtual"
    assert state.locus_locked is True
    assert state.locked_by == "development"


def test_maturation_ack_read_old_started_at(tmp_path: Path) -> None:
    path = tmp_path / "maturation_request.json"
    started = "2026-01-01T00:00:00+00:00"
    payload = {
        "request_id": uuid4().hex,
        "requested_at": "2026-01-01T00:00:01+00:00",
        OLD_RECORD_FIELD: started,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    req = maturation_ack.read_request(path)
    assert req is not None
    assert req.development_started_at == started


def test_world_model_checkpoint_header_aliases() -> None:
    cfg = SimpleNamespace(
        obs_dim=4,
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=16,
        hidden_dim=16,
        latent_kind="categorical",
    )
    params = {
        "rssm": {"w": np.zeros((2, 3), dtype=np.float32)},
        "decoder": {"b": np.ones((4,), dtype=np.float32)},
    }

    old_header = _rssm_config_header(cfg, {"encoder_version": OLD_ENCODER_VERSION})
    old_header["format"] = OLD_WORLD_MODEL_FORMAT
    blob = _encode_checkpoint(params, old_header)

    expected_header = _rssm_config_header(cfg, {"encoder_version": NEW_ENCODER_VERSION})
    decoded = _decode_checkpoint(blob, expected_header, params)

    np.testing.assert_array_equal(decoded["rssm"]["w"], params["rssm"]["w"])
    np.testing.assert_array_equal(decoded["decoder"]["b"], params["decoder"]["b"])


def test_world_model_checkpoint_unknown_format_raises() -> None:
    cfg = SimpleNamespace(
        obs_dim=4,
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=16,
        hidden_dim=16,
        latent_kind="categorical",
    )
    params = {
        "rssm": {"w": np.zeros((2, 3), dtype=np.float32)},
    }
    expected_header = _rssm_config_header(cfg, {"encoder_version": NEW_ENCODER_VERSION})

    bad_header = _rssm_config_header(cfg, {"encoder_version": NEW_ENCODER_VERSION})
    bad_header["format"] = "unknown-format-v0"
    bad_blob = _encode_checkpoint(params, bad_header)

    with pytest.raises(CheckpointMismatchError):
        _decode_checkpoint(bad_blob, expected_header, params)


def test_preservation_monitor_maps_old_drift_arm() -> None:
    arms = [OLD_SELF_MODEL_DRIFT, "some_other_arm"]
    assert _map_arms(arms) == frozenset({"self_model_drift", "some_other_arm"})


def test_preservation_monitor_arm_mapping_identity_while_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    arms = [OLD_SELF_MODEL_DRIFT, "some_other_arm"]
    assert _map_arms(arms) == frozenset({OLD_SELF_MODEL_DRIFT, "some_other_arm"})


def test_runner_reads_old_maturation_bloom_field(tmp_path: Path) -> None:
    line_dir = tmp_path / "line"
    stage_path = line_dir / "state" / "lifecycle" / "stage.json"
    stage_path.parent.mkdir(parents=True)
    ts = "2026-01-01T00:00:00+00:00"
    stage_path.write_text(
        json.dumps({OLD_MATURATION_BLOOM_FIELD: ts}), encoding="utf-8"
    )

    runner = object.__new__(StudyRunner)
    runner.wall_clock = lambda: 0.0  # type: ignore[method-assign]

    deadline = runner._read_maturation_bloom_deadline(line_dir)
    assert deadline == datetime.fromisoformat(ts).timestamp()
