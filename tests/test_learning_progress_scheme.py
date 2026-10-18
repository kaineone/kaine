# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

from kaine.experiment import write_manifest
from kaine.experiment.run_context import LEARNING_PROGRESS_SCHEME, RunContext, mint_run_context


def test_learning_progress_scheme_default():
    ctx = RunContext(run_id="r", seed=1, started_at="t", git_sha=None)
    assert ctx.learning_progress_scheme == LEARNING_PROGRESS_SCHEME == 2
    assert ctx.to_dict()["learning_progress_scheme"] == 2


def test_learning_progress_scheme_in_manifest(tmp_path):
    ctx = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    assert ctx.learning_progress_scheme == 2
    path = write_manifest(ctx, root=tmp_path)
    loaded = json.loads(path.read_text())
    assert loaded["learning_progress_scheme"] == 2
