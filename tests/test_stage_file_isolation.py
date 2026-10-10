# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""No test writes the checkout's real developmental-stage file."""

from kaine.lifecycle import stage
from kaine.storage import resolve


def test_default_stage_writes_land_in_the_test_tmp_dir(tmp_path):
    # Where an unisolated write would land: the default path under the
    # configured data root, the same resolution write_stage applies.
    real = resolve(stage.DEFAULT_STAGE_PATH).resolve()
    before = real.read_bytes() if real.exists() else None

    stage.write_stage(stage.StageState(stage=stage.GESTATION))

    assert stage.STAGE_PATH.is_relative_to(tmp_path)
    assert stage.read_stage().stage == stage.GESTATION
    after = real.read_bytes() if real.exists() else None
    assert after == before
