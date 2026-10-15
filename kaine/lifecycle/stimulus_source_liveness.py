# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus source liveness probe for the maturation gate.

There are two distinct moments:

* ``check_stimulus_source_ready`` is called before spawn.  For ``mode == "stimulus_source"`` it runs
  the local, discard-only perception probe; for any other mode it checks
  the presence contract for an external provider.
* ``check_stimulus_source_live`` is called while the entity is developing.  It checks the
  presence contract for both local and external providers.

A running local stimulus source is proven by
``kaine.cycle.stimulus_source_presence.StimulusSourcePresencePublisher`` from real deliveries.
Presence contract: an event with ``source == "development"`` and
``type == "development.stimulus_source"`` must be published to ``development.out``.  The
payload must contain ``provider`` and ``frame_index``.  A live stimulus source must
publish at least once per second and ``frame_index`` must advance.  The whole
configured window is read, not only the newest entry, because ``development.out``
also carries ``development.readiness`` events.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Awaitable, Callable

from kaine.bus.streams import DEVELOPMENT_SOURCE, DEVELOPMENT_STREAM

DEFAULT_PRESENCE_WINDOW_S = 3.0
STIMULUS_SOURCE_STREAM = DEVELOPMENT_STREAM
STIMULUS_SOURCE_SOURCE = DEVELOPMENT_SOURCE
STIMULUS_SOURCE_PRESENCE_TYPE = "development.stimulus_source"


@dataclasses.dataclass(frozen=True)
class StimulusSourceLiveness:
    live: bool
    provider: str  # "local" | "external"
    reason: str  # "" when live; a one-line cause otherwise


def _validate_window_s(window_s: float) -> None:
    if not math.isfinite(window_s) or window_s <= 0.0:
        raise ValueError(f"window_s must be finite and > 0; got {window_s!r}")


async def check_stimulus_source_ready(
    config: dict[str, Any],
    bus: Any | None,
    *,
    perception_check: Callable[[dict[str, Any]], Awaitable[list[Any]]] | None = None,
    window_s: float = DEFAULT_PRESENCE_WINDOW_S,
) -> StimulusSourceLiveness:
    _validate_window_s(window_s)

    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    if mode == "stimulus_source":
        return await _check_local_stimulus_source(config, perception_check)
    return await _check_presence(bus, window_s, local=False)


async def check_stimulus_source_live(
    config: dict[str, Any],
    bus: Any | None,
    *,
    window_s: float = DEFAULT_PRESENCE_WINDOW_S,
) -> StimulusSourceLiveness:
    _validate_window_s(window_s)

    feed = dict(config.get("perception_feed") or {})
    mode = str(feed.get("mode", "off")).lower()

    return await _check_presence(bus, window_s, local=(mode == "stimulus_source"))


async def _check_local_stimulus_source(
    config: dict[str, Any],
    perception_check: Callable[[dict[str, Any]], Awaitable[list[Any]]] | None,
) -> StimulusSourceLiveness:
    modules = dict(config.get("modules") or {})
    if not modules.get("vision"):
        return StimulusSourceLiveness(
            False,
            "local",
            "[modules].vision is disabled — the stimulus source cannot be seen",
        )
    if not modules.get("audition"):
        return StimulusSourceLiveness(
            False,
            "local",
            "[modules].audition is disabled — the stimulus source cannot be heard",
        )
    if not modules.get("interoception"):
        return StimulusSourceLiveness(
            False,
            "local",
            "[modules].interoception is disabled — the stimulus source's self-rhythm has no host",
        )

    interoception_section = dict(config.get("interoception") or {})
    if not interoception_section.get("self_rhythm_enabled"):
        return StimulusSourceLiveness(
            False,
            "local",
            "[interoception].self_rhythm_enabled is off — a developing entity needs its own rhythm",
        )

    from kaine.oscillator import snntorch_available
    if not snntorch_available():
        return StimulusSourceLiveness(
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
        return StimulusSourceLiveness(False, "local", f"{type(exc).__name__}: {exc}")

    video_pass = any(
        "video" in str(getattr(r, "name", "")).lower() and getattr(r, "status", "") == "PASS"
        for r in rows
    )
    audio_pass = any(
        "audio" in str(getattr(r, "name", "")).lower() and getattr(r, "status", "") == "PASS"
        for r in rows
    )

    if video_pass and audio_pass:
        return StimulusSourceLiveness(True, "local", "")

    failing = [
        f"{getattr(r, 'name', '?')}: {getattr(r, 'status', '?')} — {getattr(r, 'detail', '')}"
        for r in rows
        if getattr(r, "status", "") != "PASS"
    ]
    if not rows:
        reason = "perception probe returned no rows — configuration alone is not a stimulus source"
    elif not video_pass and not audio_pass:
        reason = "no video or audio PASS row; " + "; ".join(failing)
    elif not video_pass:
        reason = "no video PASS row; " + "; ".join(failing)
    else:
        reason = "no audio PASS row; " + "; ".join(failing)
    return StimulusSourceLiveness(False, "local", reason)


async def _check_presence(
    bus: Any | None,
    window_s: float,
    *,
    local: bool,
) -> StimulusSourceLiveness:
    provider_label = "local" if local else "external"

    if bus is None:
        return StimulusSourceLiveness(False, provider_label, "no bus")

    try:
        now_ms = await bus.server_time_ms()
        entries = await bus.range(
            STIMULUS_SOURCE_STREAM,
            start=str(now_ms - int(window_s * 1000)),
            end="+",
            count=None,
        )
    except Exception as exc:
        return StimulusSourceLiveness(False, provider_label, f"{type(exc).__name__}: {exc}")

    qualifying: list[int] = []
    for _id, event in entries:
        if getattr(event, "source", None) != STIMULUS_SOURCE_SOURCE:
            continue
        if getattr(event, "type", None) != STIMULUS_SOURCE_PRESENCE_TYPE:
            continue

        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue

        frame_index = payload.get("frame_index")
        if not isinstance(frame_index, int) or isinstance(frame_index, bool):
            continue

        # The running local stimulus source names itself "local"; an external provider
        # names itself (e.g. its body adapter) with anything else.
        provider = payload.get("provider")
        if local:
            if provider != "local":
                continue
        elif not isinstance(provider, str) or not provider or provider == "local":
            continue

        qualifying.append(frame_index)

    if len(qualifying) == 0:
        return StimulusSourceLiveness(
            False,
            provider_label,
            f"no {STIMULUS_SOURCE_PRESENCE_TYPE} presence event on {STIMULUS_SOURCE_STREAM} in the last {window_s:g} s",
        )
    if len(qualifying) == 1:
        return StimulusSourceLiveness(
            False,
            provider_label,
            "only one presence event in the window; a live stimulus source cannot be told from a stalled one",
        )
    if qualifying[-1] <= qualifying[0]:
        return StimulusSourceLiveness(
            False,
            provider_label,
            "frame_index did not advance: the provider is stalled or replaying",
        )
    return StimulusSourceLiveness(True, provider_label, "")
