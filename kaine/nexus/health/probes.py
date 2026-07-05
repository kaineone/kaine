# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Status vocabulary + individual dependency probe implementations.

Each ``probe_*``/``nous_health_probe`` coroutine answers one question — is
this external dependency reachable and correctly configured? — and returns
``(status, detail)``. They are pure I/O: no state, no caching (caching lives
in :class:`~kaine.nexus.health.prober.HealthProber`).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

# Status vocabulary (kept as plain strings to match the JSON contract).
UP = "up"
DOWN = "down"
DEGRADED = "degraded"
NOT_CONFIGURED = "not_configured"

DEFAULT_PROBE_TIMEOUT_S = 2.0
DEFAULT_CACHE_TTL_S = 5.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def probe_redis(*, host: str, port: int, password: str | None) -> tuple[str, str]:
    try:
        import redis.asyncio as aioredis
    except Exception:
        return DEGRADED, "redis client not importable"
    client = aioredis.Redis(
        host=host,
        port=port,
        password=password or None,
        socket_connect_timeout=1.5,
        socket_timeout=1.5,
    )
    try:
        pong = await client.ping()
        if pong:
            return UP, f"PING ok ({host}:{port})"
        return DOWN, "PING returned falsy"
    finally:
        try:
            await client.aclose()
        except Exception:
            try:
                await client.close()
            except Exception:
                pass


async def probe_qdrant(*, host: str, port: int, api_key: str | None) -> tuple[str, str]:
    url = f"http://{host}:{port}/readyz"
    headers = {"api-key": api_key} if api_key else {}
    async with httpx.AsyncClient(timeout=1.8) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 200:
        return UP, f"/readyz ok ({host}:{port})"
    return DEGRADED, f"/readyz returned HTTP {resp.status_code}"


async def probe_chat_llm(
    *, base_url: str, model_id: str | None, api_key: str | None = None
) -> tuple[str, str]:
    # Tolerate chat_url given as the server root or with a trailing /v1 (the
    # OpenAI-compat surface) — strip then hit the /v1/models listing either way.
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    url = base + "/v1/models"
    # A keyed server (Unsloth Studio) needs bearer auth or the probe 401s and
    # falsely reports degraded; keyless servers ignore the header.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    async with httpx.AsyncClient(timeout=1.8, headers=headers) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        return DEGRADED, f"/v1/models returned HTTP {resp.status_code}"
    try:
        data = resp.json()
        served = [m.get("id") for m in (data.get("data") or [])]
    except Exception:
        return DEGRADED, "could not parse /v1/models response"
    if model_id and model_id not in served:
        return (
            DEGRADED,
            f"reachable but model '{model_id}' not served ({len(served)} models present)",
        )
    return UP, f"model '{model_id}' served" if model_id else f"{len(served)} models served"


async def probe_speaches(*, base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/v1/models"
    async with httpx.AsyncClient(timeout=1.8) as client:
        resp = await client.get(url)
    if resp.status_code == 200:
        return UP, "/v1/models ok"
    return DEGRADED, f"/v1/models returned HTTP {resp.status_code}"


async def probe_chatterbox(*, base_url: str) -> tuple[str, str]:
    url = base_url.rstrip("/") + "/"
    async with httpx.AsyncClient(timeout=1.8) as client:
        resp = await client.get(url)
    # Chatterbox's root may answer 200 or a redirect / 404 while still
    # being a live listener; any HTTP response means the port is serving.
    if resp.status_code < 500:
        return UP, f"responding (HTTP {resp.status_code})"
    return DEGRADED, f"HTTP {resp.status_code}"


async def probe_state_encryption(
    *, section: dict[str, Any]
) -> tuple[str, str]:
    """Probe the state-encryption posture from [security.state_encryption].

    Three outcomes:
    - disabled → plaintext (not an error; the shipped default)
    - enabled + key resolvable → at-rest: encrypted
    - enabled + no key → fail-closed (operator action required)

    The key is NEVER read or logged; only its presence is checked.
    """
    enabled = bool(section.get("enabled", False))
    if not enabled:
        return UP, "at-rest: plaintext (encryption disabled)"

    key_env_var = str(section.get("key_env_var", "KAINE_STATE_KEY"))

    def _check_key() -> tuple[str, str]:
        import os

        # Check env var without reading the value into any log.
        if os.environ.get(key_env_var):
            return UP, "at-rest: encrypted (key resolvable via env var)"

        # Check kernel keyring without reading the value.
        try:
            import keyutils  # type: ignore

            kid = keyutils.request_key(
                "kaine:state_key", keyutils.KEY_SPEC_USER_KEYRING
            )
            if kid is not None:
                return UP, "at-rest: encrypted (key resolvable via keyring)"
        except Exception:
            # keyutils is optional and the keyring lookup is best-effort; any
            # failure (module absent, no key, keyring unavailable) must not crash
            # the probe. Fall through to the degraded/fail-closed return below.
            pass

        return (
            DEGRADED,
            f"encryption enabled but NO KEY found (set ${key_env_var} or load keyring); fail-closed",
        )

    return await asyncio.to_thread(_check_key)


async def nous_health_probe() -> tuple[str, str]:
    """Probe Nous's active-inference backend (pymdp 1.0 + JAX).

    Nous no longer wraps an external NAR binary; it runs active inference via
    pymdp/JAX (the ``reasoning`` optional extra). The probe confirms both are
    importable AND that the generative model can be built (a minimal cheap
    construction). JAX on a CPU-only host logs a one-line GPU-fallback notice
    at import — that is expected and does not affect the probe result.
    """

    def _check() -> tuple[str, str]:
        try:
            import pymdp  # noqa: F401
            import jax  # noqa: F401
        except Exception as exc:  # ImportError or backend init failure
            return DOWN, f"pymdp/jax import failed: {exc}"
        try:
            devices = ", ".join(str(d) for d in jax.devices())
        except Exception:
            devices = "unknown"
        # Importability alone is not enough — confirm the generative model
        # can actually be built with the default (compact) parameter set.
        # This catches missing numpy/dependency issues and config errors
        # that only surface at construction time, not at import time.
        try:
            from kaine.modules.nous.generative_model import build_generative_model
            build_generative_model()
        except Exception as exc:
            return DEGRADED, (
                f"pymdp + jax importable (devices: {devices}) but "
                f"generative model build failed: {exc}"
            )
        return UP, f"pymdp + jax importable; generative model built (devices: {devices})"

    return await asyncio.to_thread(_check)
