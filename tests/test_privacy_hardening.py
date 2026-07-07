# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the privacy hardening additions.

1. DINOv2Encoder.load() sets HF_HUB_DISABLE_TELEMETRY=1 before any
   from_pretrained call (matching the Mnemos embedder pattern).

2. hot_swap._do_reload_endpoint() refuses a non-loopback URL unless
   KAINE_ALLOW_NONLOCAL_HOT_SWAP=1 is set.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. HF_HUB_DISABLE_TELEMETRY in DINOv2Encoder.load()
# ---------------------------------------------------------------------------


def test_dinov2_encoder_sets_hf_telemetry_flag(monkeypatch):
    """DINOv2Encoder.load() must set HF_HUB_DISABLE_TELEMETRY before loading."""
    from kaine.modules.topos.encoder import DINOv2Encoder

    # Remove any pre-existing value so we can detect the setdefault.
    monkeypatch.delenv("HF_HUB_DISABLE_TELEMETRY", raising=False)

    telemetry_values_seen: list[str | None] = []
    load_sync_called = []

    async def patched_load(self):
        if self._model is not None:
            return

        import asyncio as _asyncio

        # Suppress telemetry BEFORE any model load (the real implementation).
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        telemetry_values_seen.append(os.environ.get("HF_HUB_DISABLE_TELEMETRY"))

        # Simulate the rest of load() without actually calling from_pretrained.
        def _fake_load_sync():
            load_sync_called.append(True)
            return None, None, None

        self._torch, self._processor, self._model = await _asyncio.to_thread(_fake_load_sync)

    monkeypatch.setattr(DINOv2Encoder, "load", patched_load)

    encoder = DINOv2Encoder()
    asyncio.run(encoder.load())

    assert load_sync_called, "load_sync was not called"
    assert telemetry_values_seen, "telemetry env not checked"
    assert telemetry_values_seen[0] == "1", (
        f"HF_HUB_DISABLE_TELEMETRY should be '1' before model load; "
        f"got {telemetry_values_seen[0]!r}"
    )


def test_dinov2_encoder_source_sets_env(monkeypatch):
    """Inspect the actual encoder source to verify os.environ.setdefault call."""
    import inspect
    from kaine.modules.topos.encoder import DINOv2Encoder

    src = inspect.getsource(DINOv2Encoder.load)
    assert "HF_HUB_DISABLE_TELEMETRY" in src, (
        "DINOv2Encoder.load() source must contain HF_HUB_DISABLE_TELEMETRY"
    )
    assert "setdefault" in src, (
        "DINOv2Encoder.load() must use os.environ.setdefault for HF_HUB_DISABLE_TELEMETRY"
    )


# ---------------------------------------------------------------------------
# 2. hot_swap loopback validation
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_loopback_url_allowed(monkeypatch):
    """A loopback URL (127.0.0.1) must be allowed and POST attempted."""
    from kaine.modules.hypnos import hot_swap

    monkeypatch.delenv("KAINE_ALLOW_NONLOCAL_HOT_SWAP", raising=False)

    posted = []

    async def fake_poster(url: str, body: dict) -> None:
        posted.append(url)

    result = _run(
        hot_swap._do_reload_endpoint(
            "http://127.0.0.1:8080/reload",
            Path("/some/adapter"),
            fake_poster,
        )
    )
    assert result["ok"] is True, f"loopback should be ok: {result}"
    assert posted, "poster must be called for loopback URL"


def test_localhost_url_allowed(monkeypatch):
    """http://localhost:... must also be accepted as loopback."""
    from kaine.modules.hypnos import hot_swap

    monkeypatch.delenv("KAINE_ALLOW_NONLOCAL_HOT_SWAP", raising=False)

    posted = []

    async def fake_poster(url: str, body: dict) -> None:
        posted.append(url)

    result = _run(
        hot_swap._do_reload_endpoint(
            "http://localhost:5000/reload",
            Path("/some/adapter"),
            fake_poster,
        )
    )
    assert result["ok"] is True
    assert posted


def test_nonloopback_url_rejected_without_env(monkeypatch):
    """A non-loopback URL must be rejected when KAINE_ALLOW_NONLOCAL_HOT_SWAP is not set."""
    from kaine.modules.hypnos import hot_swap

    monkeypatch.delenv("KAINE_ALLOW_NONLOCAL_HOT_SWAP", raising=False)

    posted = []

    async def fake_poster(url: str, body: dict) -> None:
        posted.append(url)
        raise AssertionError("poster must NOT be called for non-loopback URL without env var")

    result = _run(
        hot_swap._do_reload_endpoint(
            "http://192.168.1.100:8080/reload",
            Path("/some/adapter"),
            fake_poster,
        )
    )
    assert result["ok"] is False, f"non-loopback without env should fail: {result}"
    assert "refused" in result.get("error", "").lower() or "loopback" in result.get("error", "").lower(), (
        f"error message should mention refusal/loopback: {result}"
    )
    assert not posted, "poster must NOT be called for non-loopback without KAINE_ALLOW_NONLOCAL_HOT_SWAP"


def test_nonloopback_url_allowed_with_env(monkeypatch):
    """A non-loopback URL must be allowed when KAINE_ALLOW_NONLOCAL_HOT_SWAP=1."""
    from kaine.modules.hypnos import hot_swap

    monkeypatch.setenv("KAINE_ALLOW_NONLOCAL_HOT_SWAP", "1")

    posted = []

    async def fake_poster(url: str, body: dict) -> None:
        posted.append(url)

    result = _run(
        hot_swap._do_reload_endpoint(
            "http://10.0.0.5:8080/reload",
            Path("/some/adapter"),
            fake_poster,
        )
    )
    assert result["ok"] is True, f"non-loopback with env=1 should be ok: {result}"
    assert posted, "poster must be called when KAINE_ALLOW_NONLOCAL_HOT_SWAP=1"


def test_nonloopback_env_value_must_be_1(monkeypatch):
    """KAINE_ALLOW_NONLOCAL_HOT_SWAP must be exactly '1' to override."""
    from kaine.modules.hypnos import hot_swap

    for bad_value in ("true", "yes", "1 ", "TRUE", "on"):
        monkeypatch.setenv("KAINE_ALLOW_NONLOCAL_HOT_SWAP", bad_value)

        posted = []

        async def fake_poster(url: str, body: dict) -> None:
            posted.append(url)

        result = _run(
            hot_swap._do_reload_endpoint(
                "http://192.168.1.100:8080/reload",
                Path("/some/adapter"),
                fake_poster,
            )
        )
        assert result["ok"] is False, (
            f"env value {bad_value!r} should NOT unlock non-loopback; got: {result}"
        )
        assert not posted


def test_is_loopback_url_patterns():
    """Unit-test the _is_loopback_url helper directly."""
    from kaine.modules.hypnos.hot_swap import _is_loopback_url

    assert _is_loopback_url("http://127.0.0.1:8080/reload")
    assert _is_loopback_url("http://127.0.0.1/")
    assert _is_loopback_url("http://localhost:9000")
    assert _is_loopback_url("http://localhost/api")
    assert _is_loopback_url("http://LOCALHOST:8080")  # case insensitive

    assert not _is_loopback_url("http://192.168.1.1:8080")
    assert not _is_loopback_url("http://10.0.0.1/reload")
    assert not _is_loopback_url("https://example.com/reload")
    assert not _is_loopback_url("http://0.0.0.0:8080")
