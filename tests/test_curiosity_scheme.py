# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

from kaine.experiment import write_manifest
from kaine.experiment.run_context import CURIOSITY_SCHEME, RunContext, mint_run_context
from kaine.faithful.templates import felt_drive_phrase


def test_curiosity_scheme_default():
    ctx = RunContext(run_id="r", seed=1, started_at="t", git_sha=None)
    assert ctx.curiosity_scheme == CURIOSITY_SCHEME == 2
    assert ctx.to_dict()["curiosity_scheme"] == 2


def test_curiosity_scheme_in_manifest(tmp_path):
    ctx = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    assert ctx.curiosity_scheme == 2
    path = write_manifest(ctx, root=tmp_path)
    loaded = json.loads(path.read_text())
    assert loaded["curiosity_scheme"] == 2


def test_felt_curiosity_phrases():
    assert felt_drive_phrase("curiosity", 0.85) == "I feel absorbed in what I am learning."
    assert felt_drive_phrase("curiosity", 0.75) == "I feel curious."
