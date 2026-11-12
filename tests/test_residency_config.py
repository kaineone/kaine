# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.config import ConfigShapeError
from kaine.residency.config import from_config


def test_defaults_from_empty_config():
    cfg = from_config({})
    assert cfg.enabled is False
    assert cfg.reserve_bytes is None
    assert cfg.ttl_seconds == 120
    assert cfg.ttl_overrides == {}
    assert cfg.pin == "language"
    assert cfg.prewarm == ()
    assert cfg.llm_proxy == "none"
    assert cfg.interactive_queue_max == 16
    assert cfg.background_queue_max == 64
    assert cfg.perception_queue_max == 32
    assert cfg.perception_queue_max_age_s == 10.0


def test_all_fields_set():
    cfg = from_config({"residency": {
        "enabled": True, "reserve_bytes": 2147483648,
        "ttl_seconds": 60, "ttl_overrides": {"stt": 30, "tts": 45},
        "pin": "none", "prewarm": ["stt", "tts"], "llm_proxy": "llama-swap",
        "interactive_queue_max": 8, "background_queue_max": 32,
        "perception_queue_max": 16, "perception_queue_max_age_s": 5.0,
    }})
    assert cfg.enabled is True
    assert cfg.reserve_bytes == 2147483648
    assert cfg.ttl_seconds == 60
    assert cfg.ttl_overrides == {"stt": 30, "tts": 45}
    assert cfg.pin == "none"
    assert cfg.prewarm == ("stt", "tts")
    assert cfg.llm_proxy == "llama-swap"
    assert cfg.interactive_queue_max == 8
    assert cfg.background_queue_max == 32
    assert cfg.perception_queue_max == 16
    assert cfg.perception_queue_max_age_s == 5.0


def test_enabled_wrong_type():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"enabled": "yes"}})


def test_reserve_negative():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"reserve_bytes": -1}})


def test_reserve_wrong_type():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"reserve_bytes": "1G"}})


def test_ttl_negative():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"ttl_seconds": -1}})


def test_llm_proxy_invalid():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"llm_proxy": "invalid"}})


def test_prewarm_not_list():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"prewarm": "stt"}})


def test_prewarm_non_string_item():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"prewarm": [123]}})


def test_queue_max_zero():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"interactive_queue_max": 0}})


def test_frozen():
    cfg = from_config({})
    with pytest.raises(AttributeError):
        cfg.enabled = True


def test_ttl_overrides_wrong_value_type():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"ttl_overrides": {"stt": "fast"}}})


def test_ttl_zero_allowed():
    cfg = from_config({"residency": {"ttl_seconds": 0}})
    assert cfg.ttl_seconds == 0


def test_perception_queue_max_zero():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"perception_queue_max": 0}})


def test_perception_queue_max_age_negative():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"perception_queue_max_age_s": -1.0}})


def test_perception_queue_max_age_wrong_type():
    with pytest.raises(ConfigShapeError):
        from_config({"residency": {"perception_queue_max_age_s": "fast"}})


def test_perception_queue_int_age_coerced():
    cfg = from_config({"residency": {"perception_queue_max_age_s": 5}})
    assert cfg.perception_queue_max_age_s == 5.0
    assert isinstance(cfg.perception_queue_max_age_s, float)
