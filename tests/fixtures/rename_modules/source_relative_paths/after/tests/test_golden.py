# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "world_model_golden"
CODE = "np.load('tests/fixtures/world_model_golden/a.npz', allow_pickle=False)"
STATE = Path("state") / "phantasia" / "world_model.ckpt"
