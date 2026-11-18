import json
import os


def test_checkpoint_config_local_path():
    checkpoint_dir = os.environ.get("CHECKPOINT_DIR", "checkpoints/custom_voice")
    with open(os.path.join(checkpoint_dir, "config.json"), "r", encoding="utf-8") as f:
        config = json.load(f)

    assert config["spk_id"]["sam"] == 3000
    assert config["tts_model_type"] == "custom_voice"
