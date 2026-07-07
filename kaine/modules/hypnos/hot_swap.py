# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lingua hot-swap dispatcher.

After a voice-alignment adapter is accepted, Hypnos calls
`dispatch()` with the new adapter path. The behavior depends on the
operator-configured `hot_swap_mode`:

- `"manual"` (default, shipped). Writes a marker file at
  `<adapter_output_dir>/PENDING_OPERATOR_RELOAD` containing the new
  adapter path and logs a one-liner pointing the operator at the
  reload step. No network or service call.
- `"reload_endpoint"`. POSTs to a configured Unsloth Studio reload
  endpoint with body `{"adapter_path": "<path>"}`. Failures are
  logged but do not raise — the adapter is already promoted.
- `"restart_service"`. Invokes `systemctl --user restart <unit>`
  against a configured unit name. Same failure semantics.

Failures are logged but do not raise. The adapter on disk is the
source of truth; hot-swap is best-effort notification only.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Awaitable, Callable, Optional

import asyncio

log = logging.getLogger(__name__)


VALID_MODES = ("manual", "reload_endpoint", "restart_service")
MANUAL_MARKER = "PENDING_OPERATOR_RELOAD"

# Loopback patterns accepted by default for the reload endpoint.
# Matches http://127.0.0.1[:port][/...] and http://localhost[:port][/...].
_LOOPBACK_RE = re.compile(
    r"^https?://(127\.0\.0\.1|localhost)(:\d+)?(/.*)?$", re.IGNORECASE
)
# Environment variable that permits a non-loopback hot-swap endpoint.
_ALLOW_NONLOCAL_ENV = "KAINE_ALLOW_NONLOCAL_HOT_SWAP"


def _is_loopback_url(url: str) -> bool:
    """Return True iff *url* is a loopback (127.0.0.1 or localhost) address."""
    return bool(_LOOPBACK_RE.match(url))


HttpPoster = Callable[[str, dict], Awaitable[None]]
ServiceRunner = Callable[[list[str]], Awaitable[int]]


async def dispatch(
    *,
    mode: str,
    adapter_output_dir: Path,
    adapter_path: Path,
    reload_endpoint_url: Optional[str] = None,
    restart_service_unit: Optional[str] = None,
    http_poster: Optional[HttpPoster] = None,
    service_runner: Optional[ServiceRunner] = None,
) -> dict:
    """Run the configured hot-swap action. Returns a small status dict.

    `http_poster` and `service_runner` are dependency-injection
    seams for tests; if omitted, real implementations are used.
    """
    if mode not in VALID_MODES:
        log.error(
            "unknown hot_swap_mode=%r; expected one of %s",
            mode,
            VALID_MODES,
        )
        return {"mode": mode, "ok": False, "error": "unknown mode"}

    if mode == "manual":
        return _do_manual(adapter_output_dir, adapter_path)
    if mode == "reload_endpoint":
        return await _do_reload_endpoint(
            reload_endpoint_url, adapter_path, http_poster
        )
    if mode == "restart_service":
        return await _do_restart_service(
            restart_service_unit, service_runner
        )
    # Unreachable given VALID_MODES check above.
    return {"mode": mode, "ok": False, "error": "unreachable"}


def _do_manual(adapter_output_dir: Path, adapter_path: Path) -> dict:
    adapter_output_dir.mkdir(parents=True, exist_ok=True)
    marker = adapter_output_dir / MANUAL_MARKER
    marker.write_text(str(adapter_path) + "\n", encoding="utf-8")
    log.info(
        "voice-alignment adapter accepted; manual reload pending. "
        "marker=%s adapter=%s",
        marker,
        adapter_path,
    )
    return {"mode": "manual", "ok": True, "marker": str(marker)}


async def _do_reload_endpoint(
    url: Optional[str],
    adapter_path: Path,
    http_poster: Optional[HttpPoster],
) -> dict:
    if not url:
        log.error(
            "hot_swap_mode=reload_endpoint but reload_endpoint_url is unset"
        )
        return {
            "mode": "reload_endpoint",
            "ok": False,
            "error": "reload_endpoint_url not configured",
        }
    # Privacy / egress guard: reject non-loopback URLs unless the operator
    # has explicitly set KAINE_ALLOW_NONLOCAL_HOT_SWAP=1.
    if not _is_loopback_url(url):
        allow_nonlocal = os.environ.get(_ALLOW_NONLOCAL_ENV) == "1"
        if not allow_nonlocal:
            log.error(
                "hot_swap reload_endpoint_url=%r is not a loopback address "
                "(127.0.0.1 or localhost). Refusing to POST. "
                "Set KAINE_ALLOW_NONLOCAL_HOT_SWAP=1 to override.",
                url,
            )
            return {
                "mode": "reload_endpoint",
                "ok": False,
                "error": (
                    f"reload_endpoint_url {url!r} is not a loopback address; "
                    "refused. Set KAINE_ALLOW_NONLOCAL_HOT_SWAP=1 to allow."
                ),
            }
        log.warning(
            "hot_swap: non-loopback reload_endpoint_url=%r allowed by "
            "KAINE_ALLOW_NONLOCAL_HOT_SWAP=1",
            url,
        )
    poster = http_poster or _default_http_poster
    try:
        await poster(url, {"adapter_path": str(adapter_path)})
    except Exception as exc:
        log.exception("reload_endpoint POST failed url=%s", url)
        return {
            "mode": "reload_endpoint",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"mode": "reload_endpoint", "ok": True, "url": url}


async def _do_restart_service(
    unit: Optional[str],
    service_runner: Optional[ServiceRunner],
) -> dict:
    if not unit:
        log.error(
            "hot_swap_mode=restart_service but restart_service_unit is unset"
        )
        return {
            "mode": "restart_service",
            "ok": False,
            "error": "restart_service_unit not configured",
        }
    runner = service_runner or _default_service_runner
    cmd = ["systemctl", "--user", "restart", unit]
    try:
        rc = await runner(cmd)
    except Exception as exc:
        log.exception("restart_service failed unit=%s", unit)
        return {
            "mode": "restart_service",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if rc != 0:
        log.error("restart_service unit=%s exited with rc=%d", unit, rc)
        return {
            "mode": "restart_service",
            "ok": False,
            "unit": unit,
            "rc": rc,
        }
    return {"mode": "restart_service", "ok": True, "unit": unit}


async def _default_http_poster(url: str, body: dict) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()


async def _default_service_runner(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    await proc.communicate()
    return int(proc.returncode or 0)
