# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Round-trip tests for StageState persistence."""

import dataclasses
import json

from kaine.lifecycle import stage

VALUES = [
    stage.EMBODIED,
    "2026-01-01T00:00:00+00:00",
    "2026-02-01T00:00:00+00:00",
    123.5,
    4,
    "17-2",
    9.5,
    42,
    "a" * 64,
    "2026-02-02T00:00:00+00:00",
]


def test_stage_state_round_trip(tmp_path):
    fields = dataclasses.fields(stage.StageState)
    assert len(VALUES) == len(fields)

    kwargs = {f.name: VALUES[i] for i, f in enumerate(fields)}
    state = stage.StageState(**kwargs)

    for f in fields:
        default = (
            f.default_factory()
            if f.default is dataclasses.MISSING and f.default_factory is not dataclasses.MISSING
            else f.default
        )
        if default is not dataclasses.MISSING:
            assert getattr(state, f.name) != default

    assert stage.StageState.from_dict(state.to_dict()) == state

    json_round_trip = json.loads(json.dumps(state.to_dict()))
    assert stage.StageState.from_dict(json_round_trip) == state

    stage_path = tmp_path / "stage.json"
    stage.write_stage(state, stage_path)
    assert stage.read_stage(stage_path) == state
