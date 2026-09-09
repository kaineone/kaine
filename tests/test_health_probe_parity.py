# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Probe/runtime parity for the health prober's dependency specs.

Covers the two pre-boot dry-run failures on a healthy stack:
  * Redis probe must honor KAINE_REDIS_URL like the real bus does.
  * Speaches must SKIP (not_configured) when transcription is disabled.
"""
from __future__ import annotations

import asyncio

from kaine.nexus.health.config import build_dependency_specs
from kaine.nexus.health.probes import NOT_CONFIGURED


def _specs(monkeypatch, *, redis_env=None, audition_cfg=None):
    monkeypatch.delenv("KAINE_REDIS_URL", raising=False)
    if redis_env is not None:
        monkeypatch.setenv("KAINE_REDIS_URL", redis_env)
    return build_dependency_specs(
        redis_cfg={"host": "127.0.0.1", "port": 6379},
        qdrant_cfg={},
        qdrant_secret_key=None,
        redis_password=None,
        lingua_cfg={},
        audition_cfg=audition_cfg or {},
        vox_cfg={},
        nous_cfg={},
        state_encryption_cfg=None,
    )


def _spec_named(specs, name):
    matches = [s for s in specs if s.name == name]
    assert len(matches) == 1
    return matches[0]


def _capture_redis_probe(spec):
    """Intercept probe_redis's arguments by faking the redis client."""
    captured = {}

    class FakeRedis:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def ping(self):
            return True

        async def aclose(self):
            return None

    import redis.asyncio as aioredis
    import sys

    real_redis = aioredis.Redis
    aioredis.Redis = FakeRedis
    try:
        result = asyncio.run(spec.probe())
    finally:
        aioredis.Redis = real_redis
    return captured, result


class TestRedisUrlOverride:
    def test_url_with_password(self, monkeypatch):
        specs = _specs(
            monkeypatch,
            redis_env="redis://:s3cret@redis-bus.example.com:6380/2",
        )
        captured, result = _capture_redis_probe(_spec_named(specs, "Redis"))
        assert captured["host"] == "redis-bus.example.com"
        assert captured["port"] == 6380
        assert captured["password"] == "s3cret"
        assert result[0] == "up"

    def test_url_without_password_keeps_fallback(self, monkeypatch):
        specs = _specs(monkeypatch, redis_env="redis://redis-bus.example.com:6380")
        captured, _ = _capture_redis_probe(_spec_named(specs, "Redis"))
        assert captured["host"] == "redis-bus.example.com"
        assert captured["port"] == 6380
        assert captured["password"] is None

    def test_url_password_beats_passed_password(self, monkeypatch):
        monkeypatch.delenv("KAINE_REDIS_URL", raising=False)
        monkeypatch.setenv("KAINE_REDIS_URL", "redis://:urlpw@redis-bus:6379")
        specs = build_dependency_specs(
            redis_cfg={"host": "127.0.0.1", "port": 6379},
            qdrant_cfg={},
            qdrant_secret_key=None,
            redis_password="fallback-pw",
            lingua_cfg={},
            audition_cfg={},
            vox_cfg={},
            nous_cfg={},
        )
        captured, _ = _capture_redis_probe(_spec_named(specs, "Redis"))
        assert captured["password"] == "urlpw"

    def test_toml_fallback_when_env_unset(self, monkeypatch):
        specs = _specs(monkeypatch)
        captured, _ = _capture_redis_probe(_spec_named(specs, "Redis"))
        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 6379
        assert captured["password"] is None

    def test_url_without_port_defaults_to_url_scheme_port(self, monkeypatch):
        # redis:// with no port -> 6379 default, host from URL.
        specs = _specs(monkeypatch, redis_env="redis://redis-bus.example.com")
        captured, _ = _capture_redis_probe(_spec_named(specs, "Redis"))
        assert captured["host"] == "redis-bus.example.com"
        assert captured["port"] == 6379


class TestSpeachesTranscriptionGating:
    def test_speaches_skips_when_transcription_disabled(self, monkeypatch):
        specs = _specs(
            monkeypatch, audition_cfg={"transcription_enabled": False}
        )
        spec = _spec_named(specs, "Speaches (STT)")

        probed = []
        from kaine.nexus.health import probes as probes_mod

        async def fake_speaches(**kwargs):
            probed.append(kwargs)
            return "up", "should not happen"

        monkeypatch.setattr(probes_mod, "probe_speaches", fake_speaches)
        status, detail = asyncio.run(spec.probe())
        assert status == NOT_CONFIGURED
        assert "transcription" in detail.lower()
        assert probed == []  # never contacted the service

    def test_speaches_probes_when_transcription_enabled(self, monkeypatch):
        specs = _specs(
            monkeypatch,
            audition_cfg={"transcription_enabled": True, "speaches_url": "http://stt:8000"},
        )
        spec = _spec_named(specs, "Speaches (STT)")

        # config.py imports probe_speaches BY NAME, so patch its binding
        # (patching the probes module attr would not reach the lambda).
        from kaine.nexus.health import config as config_mod

        async def fake_speaches(*, base_url):
            return "up", f"speaches ok at {base_url}"

        monkeypatch.setattr(config_mod, "probe_speaches", fake_speaches)
        status, detail = asyncio.run(spec.probe())
        assert status == "up"
        assert detail == "speaches ok at http://stt:8000"

    def test_speaches_defaults_to_enabled_when_unset(self, monkeypatch):
        # transcription_enabled absent -> default True -> probe path.
        specs = _specs(monkeypatch, audition_cfg={})
        spec = _spec_named(specs, "Speaches (STT)")

        from kaine.nexus.health import config as config_mod

        async def fake_speaches(*, base_url):
            return "up", "ok"

        monkeypatch.setattr(config_mod, "probe_speaches", fake_speaches)
        status, _ = asyncio.run(spec.probe())
        assert status == "up"
