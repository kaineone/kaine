# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Golden pins: stored stimulus-source parameter bytes never change with a Python rename."""

import hashlib
import json
from dataclasses import fields

import kaine.legacy_names as legacy_names
from kaine.boot.perception_feed import gather_perception_feed_descriptor
from kaine.lifecycle.stage import womb_params_digest
from kaine.lifecycle.stored_field_names import (
    STIMULUS_SOURCE_PARAMS,
    stimulus_source_params_record,
)
from kaine.modules.stimulus_source_signal import StimulusSourceParams

GOLDEN_DEFAULT_DIGEST = (
    "e21261c7333394e2a22ab7f39b7e142502adb38110aa9e7e207d4158ab58396b"
)
# the digest of the default parameters before the rename; stage.json files of matured
# entities hold it.


def test_default_params_digest_is_golden() -> None:
    assert womb_params_digest(StimulusSourceParams()) == GOLDEN_DEFAULT_DIGEST


def test_record_uses_stored_field_names() -> None:
    record = stimulus_source_params_record(StimulusSourceParams())
    assert "birth_transition_seconds" in record
    assert "maturation_transition_seconds" not in record
    expected = [
        STIMULUS_SOURCE_PARAMS.get(field.name, field.name)
        for field in fields(StimulusSourceParams)
    ]
    assert sorted(record) == sorted(expected)


def test_feed_descriptor_bytes_are_golden() -> None:
    desc = gather_perception_feed_descriptor(
        {"perception_feed": {"mode": "womb", "seed": 3}}
    )
    payload = json.dumps(desc["womb"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == GOLDEN_DEFAULT_DIGEST


def test_non_default_value_round_trips_under_stored_name() -> None:
    params = StimulusSourceParams.from_sections(
        {"birth_transition_seconds": 7.5}, None, None
    )
    assert stimulus_source_params_record(params)["birth_transition_seconds"] == 7.5


def test_stored_names_are_frozen_pre_rename_config_keys() -> None:
    """Stored names are the config keys from before the rename, and the codemod never rewrites them."""
    assert "kaine/lifecycle/stored_field_names.py" in legacy_names.EXCLUDED_GLOBS
    assert "tests/test_stimulus_source_params_digest.py" in legacy_names.EXCLUDED_GLOBS
    for field, stored in STIMULUS_SOURCE_PARAMS.items():
        assert stored != field
        assert any(e["old"] == stored and e["new"] == field for e in legacy_names.CONFIG_KEYS)
