# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Womb liveness probe for the maturation gate.

Two providers: local (the in-process womb perception feed) and external (a
gestation peripheral publishing presence events). The gate calls this function
and does not change when a provider is swapped; only the configuration does.

Presence contract (external provider): an event with
``source == "gestation"`` and ``type == "gestation.womb"`` must be published to
``gestation.out`` at least once per second. The payload must contain
``provider`` and ``frame_index``. The probe reads the whole configured time
window, not only the newest entry, because ``gestation.out`` also carries
``gestation.readiness`` events.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Awaitable, Callable

DEFAULT_PRESENCE_WINDOW_S = 3.0
WOMB_STREAM = "gestation.out"
WOMB_SOURCE = "gestation"
WOMB_PRESENCE_TYPE = "gestation.womb"


@dataclasses.dataclass(frozen=True)
class WombLiveness:
    live: bool
    provider: str  # "local" | "external"
    reason: str  # "" when live; a one-line cause otherwise


async def check_womb_liveness(
    config: dict[str, Any],
    bus: Any | None,
    *,
    perception_check: Callable[[dict[str, Any]], Awaitable[list[Any]]] | None = None,
    window_s: float = DEFAULT_PRESENCE_WINDOW_S,
) -> WombLiveness:
    if not math.isfinite(window_s) or window_s <= 0.0:
        raise ValueError(f"window_s must be finite and > 0; got {window_s!r}")

    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    if mode == "womb":
        return await _check_local_womb(config, perception_check)
    return await _check_external_womb(bus, window_s)


async def _check_local_womb(
    config: dict[str, Any],
    perception_check: Callable[[dict[str, Any]], Awaitable[list[Any]]] | None,
) -> WombLiveness:
    modules = dict(config.get("modules") or {})
    if not modules.get("topos"):
        return WombLiveness(
            False,
            "local",
            "[modules].topos is disabled — the womb cannot be seen",
        )
    if not modules.get("audition"):
        return WombLiveness(
            False,
            "local",
            "[modules].audition is disabled — the womb cannot be heard",
        )

    probe = perception_check
    if probe is None:
        from kaine.preboot import check_perception

        probe = check_perception

    try:
        rows = await probe(config)
    except Exception as exc:
        return WombLiveness(False, "local", f"{type(exc).__name__}: {exc}")

    video_pass = any(
        "video" in str(getattr(r, "name", "")).lower() and getattr(r, "status", "") == "PASS"
        for r in rows
    )
    audio_pass = any(
        "audio" in str(getattr(r, "name", "")).lower() and getattr(r, "status", "") == "PASS"
        for r in rows
    )

    if video_pass and audio_pass:
        return WombLiveness(True, "local", "")

    failing = [
        f"{getattr(r, 'name', '?')}: {getattr(r, 'status', '?')} — {getattr(r, 'detail', '')}"
        for r in rows
        if getattr(r, "status", "") != "PASS"
    ]
    if not rows:
        reason = "perception probe returned no rows — configuration alone is not a womb"
    elif not video_pass and not audio_pass:
        reason = "no video or audio PASS row; " + "; ".join(failing)
    elif not video_pass:
        reason = "no video PASS row; " + "; ".join(failing)
    else:
        reason = "no audio PASS row; " + "; ".join(failing)
    return WombLiveness(False, "local", reason)


async def _check_external_womb(bus: Any | None, window_s: float) -> WombLiveness:
    if bus is None:
        return WombLiveness(False, "external", "no bus")

    try:
        now_ms = await bus.server_time_ms()
        entries = await bus.range(
            WOMB_STREAM,
            start=str(now_ms - int(window_s * 1000)),
            end="+",
            count=None,
        )
    except Exception as exc:
        return WombLiveness(False, "external", f"{type(exc).__name__}: {exc}")

    for _id, event in entries:
        if (
            getattr(event, "source", None) == WOMB_SOURCE
            and getattr(event, "type", None) == WOMB_PRESENCE_TYPE
        ):
            return WombLiveness(True, "external", "")

    return WombLiveness(
        False,
        "external",
        f"no {WOMB_PRESENCE_TYPE} presence event on {WOMB_STREAM} in the last {window_s:g} s",
    )
