# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.experiment.run_context import CONFIG_KEY_SCHEME, RunContext


def test_config_key_scheme_default():
    ctx = RunContext(run_id="r", seed=1, started_at="t", git_sha=None)
    assert ctx.config_key_scheme == CONFIG_KEY_SCHEME == 2
    assert ctx.to_dict()["config_key_scheme"] == 2
