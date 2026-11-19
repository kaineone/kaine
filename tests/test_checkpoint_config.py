# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os

import pytest


def test_checkpoint_config_local_path():
    checkpoint_dir = os.environ.get("CHECKPOINT_DIR", "checkpoints/custom_voice")
    config_path = os.path.join(checkpoint_dir, "config.json")
    if not os.path.exists(config_path):
        pytest.skip("checkpoint fixture not present")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    assert config["spk_id"]["sam"] == 3000
    assert config["tts_model_type"] == "custom_voice"
