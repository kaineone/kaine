# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Womb liveness probe for the maturation gate.

There are two distinct moments:

* ``check_womb_ready`` is called before spawn.  For ``mode == "womb"`` it runs
  the local, discard-only perception probe; for any other mode it checks
  the presence contract for an external provider.
* ``check_womb_live`` is called while the entity is gestating.  It checks the
  presence contract for both local and external providers.

A running local womb is proven by
``kaine.cycle.womb_presence.WombPresencePublisher`` from real deliveries.
Presence contract: an event with ``source == "gestation"`` and
``type == "gestation.womb"`` must be published to ``gestation.out``.  The
payload must contain ``provider`` and ``frame_index``.  A live womb must
publish at least once per second and ``frame_index`` must advance.  The whole
configured window is read, not only the newest entry, because ``gestation.out``
also carries ``gestation.readiness`` events.
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


def _validate_window_s(window_s: float) -> None:
    if not math.isfinite(window_s) or window_s <= 0.0:
        raise ValueError(f"window_s must be finite and > 0; got {window_s!r}")


async def check_womb_ready(
    config: dict[str, Any],
    bus: Any | None,
    *,
    perception_check: Callable[[dict[str, Any]], Awaitable[list[Any]]] | None = None,
    window_s: float = DEFAULT_PRESENCE_WINDOW_S,
) -> WombLiveness:
    _validate_window_s(window_s)

    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    if mode == "womb":
        return await _check_local_womb(config, perception_check)
    return await _check_presence(bus, window_s, local=False)


async def check_womb_live(
    config: dict[str, Any],
    bus: Any | None,
    *,
    window_s: float = DEFAULT_PRESENCE_WINDOW_S,
) -> WombLiveness:
    _validate_window_s(window_s)

    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    return await _check_presence(bus, window_s, local=(mode == "womb"))


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
    if not modules.get("soma"):
        return WombLiveness(
            False,
            "local",
            "[modules].soma is disabled — the womb's self-rhythm has no host",
        )

    soma_section = dict(config.get("soma") or {})
    if not soma_section.get("self_rhythm_enabled"):
        return WombLiveness(
            False,
            "local",
            "[soma].self_rhythm_enabled is off — a gestating entity needs its own rhythm",
        )

    from kaine.oscillator import snntorch_available
    if not snntorch_available():
        return WombLiveness(
            False,
            "local",
            "the oscillator extra (snnTorch) is not installed",
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


async def _check_presence(
    bus: Any | None,
    window_s: float,
    *,
    local: bool,
) -> WombLiveness:
    provider_label = "local" if local else "external"

    if bus is None:
        return WombLiveness(False, provider_label, "no bus")

    try:
        now_ms = await bus.server_time_ms()
        entries = await bus.range(
            WOMB_STREAM,
            start=str(now_ms - int(window_s * 1000)),
            end="+",
            count=None,
        )
    except Exception as exc:
        return WombLiveness(False, provider_label, f"{type(exc).__name__}: {exc}")

    qualifying: list[int] = []
    for _id, event in entries:
        if getattr(event, "source", None) != WOMB_SOURCE:
            continue
        if getattr(event, "type", None) != WOMB_PRESENCE_TYPE:
            continue

        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue

        frame_index = payload.get("frame_index")
        if not isinstance(frame_index, int) or isinstance(frame_index, bool):
            continue

        # The running local womb names itself "local"; an external provider
        # names itself (e.g. its body adapter) with anything else.
        provider = payload.get("provider")
        if local:
            if provider != "local":
                continue
        elif not isinstance(provider, str) or not provider or provider == "local":
            continue

        qualifying.append(frame_index)

    if len(qualifying) == 0:
        return WombLiveness(
            False,
            provider_label,
            f"no {WOMB_PRESENCE_TYPE} presence event on {WOMB_STREAM} in the last {window_s:g} s",
        )
    if len(qualifying) == 1:
        return WombLiveness(
            False,
            provider_label,
            "only one presence event in the window; a live womb cannot be told from a stalled one",
        )
    if qualifying[-1] <= qualifying[0]:
        return WombLiveness(
            False,
            provider_label,
            "frame_index did not advance: the provider is stalled or replaying",
        )
    return WombLiveness(True, provider_label, "")
