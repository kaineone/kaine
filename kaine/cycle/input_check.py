# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Continuous input gate and runtime input-loss watcher.

This module implements condition 8 of the unattended boot gate
("continuous input") and the running caretaker notice that fires when
all configured perception streams stop producing data.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kaine.cycle.unattended_gate import Condition

log = logging.getLogger(__name__)


def check_input_condition(
    config: dict[str, Any],
    *,
    camera_factory: Callable[..., Any] | None = None,
    mic_factory: Callable[..., Any] | None = None,
    perception_check: Callable[..., Any] | None = None,
    timeout_s: float = 3.0,
) -> "Condition":
    """Verify the entity has a continuous perception input.

    The probe is intentionally stateless: raw frames and audio blocks are
    dropped immediately and nothing is written to disk.
    """
    from kaine.cycle.unattended_gate import CONDITION_NAMES, Condition

    try:
        feed = dict(config.get("perception_feed") or {})
        mode = str(feed.get("mode", "off")).lower()

        if mode == "off":
            return Condition(
                number=8,
                name=CONDITION_NAMES[8],
                ok=False,
                reason="no input: [perception_feed].mode is off",
            )
        if mode == "playlist":
            return Condition(
                number=8,
                name=CONDITION_NAMES[8],
                ok=False,
                reason=(
                    "playlist ends: a playlist runs out, leaving the entity without input"
                ),
            )
        if mode not in ("live", "seeded", "screen"):
            return Condition(
                number=8,
                name=CONDITION_NAMES[8],
                ok=False,
                reason="unsupported perception mode",
            )

        modules = dict(config.get("modules") or {})
        topos_on = bool(modules.get("topos"))
        audition_on = bool(modules.get("audition"))

        surfaces: list[tuple[str, Callable[..., tuple[bool, str]], tuple[Any, ...]]] = []

        if mode == "live":
            topos_cfg = dict(config.get("topos") or {})
            audition_cfg = dict(config.get("audition") or {})
            topos_ready = topos_on and bool(topos_cfg.get("capture_enabled"))
            audition_ready = audition_on and bool(audition_cfg.get("capture_enabled"))

            if not (topos_ready or audition_ready):
                return Condition(
                    number=8,
                    name=CONDITION_NAMES[8],
                    ok=False,
                    reason=(
                        "no perceiving module: enable topos or audition with capture_enabled"
                    ),
                )

            if topos_ready:
                surfaces.append(
                    ("camera", _probe_camera, (topos_cfg, camera_factory))
                )
            if audition_ready:
                surfaces.append(
                    (
                        "microphone",
                        _probe_microphone,
                        (audition_cfg, mic_factory, timeout_s),
                    )
                )
        else:
            if not (topos_on or audition_on):
                return Condition(
                    number=8,
                    name=CONDITION_NAMES[8],
                    ok=False,
                    reason="no perceiving module: enable topos or audition",
                )

            if topos_on:
                surfaces.append(
                    ("video source", _probe_seeded_video, (perception_check, config))
                )
            if audition_on:
                surfaces.append(
                    ("audio source", _probe_seeded_audio, (perception_check, config))
                )

        delivered = 0
        failure_lines: list[str] = []

        for name, probe, args in surfaces:
            try:
                ok, detail = probe(*args)
            except Exception as exc:
                failure_lines.append(f"{name}: {type(exc).__name__}: {exc}")
            else:
                if ok:
                    delivered += 1
                else:
                    failure_lines.append(f"{name}: {detail}")

        if delivered > 0:
            return Condition(number=8, name=CONDITION_NAMES[8], ok=True, reason="")

        return Condition(
            number=8,
            name=CONDITION_NAMES[8],
            ok=False,
            reason="no input delivered: " + "; ".join(failure_lines),
        )

    except Exception as exc:
        return Condition(
            number=8,
            name=CONDITION_NAMES[8],
            ok=False,
            reason=f"{type(exc).__name__}: {exc}",
        )


def _probe_camera(
    topos_cfg: dict[str, Any], camera_factory: Callable[..., Any] | None
) -> tuple[bool, str]:
    if camera_factory is None:
        from kaine.modules.topos.live import _default_source_factory as camera_factory

    device = topos_cfg.get("capture_device", 0)
    width = topos_cfg.get("capture_width")
    height = topos_cfg.get("capture_height")

    source = camera_factory(device, width=width, height=height)
    try:
        if not source.open():
            return False, "device could not be opened"
        ok, frame = source.read()
        if not ok or frame is None:
            return False, "read returned empty frame"
        del frame
        return True, ""
    finally:
        try:
            source.release()
        except Exception:
            log.debug("camera release raised", exc_info=True)


def _probe_microphone(
    audition_cfg: dict[str, Any],
    mic_factory: Callable[..., Any] | None,
    timeout_s: float,
) -> tuple[bool, str]:
    if mic_factory is None:
        from kaine.modules.audition.live import _default_stream_factory as mic_factory

    device = audition_cfg.get("capture_device")
    # The same keys and block size the boot uses to open the live microphone.
    sample_rate = int(audition_cfg.get("capture_sample_rate", 16000))
    channels = int(audition_cfg.get("capture_channels", 1))
    vad_frame_ms = int(audition_cfg.get("vad_frame_ms", 30))
    frames_per_block = max(1, sample_rate * vad_frame_ms // 1000)

    got_block = threading.Event()

    def callback(block: bytes) -> None:
        if block:
            got_block.set()

    stream = mic_factory(
        device=device,
        sample_rate=sample_rate,
        channels=channels,
        frames_per_block=frames_per_block,
        callback=callback,
    )
    try:
        stream.start()
        got_block.wait(timeout=timeout_s)
        if not got_block.is_set():
            return False, f"no audio block delivered within {timeout_s}s"
        return True, ""
    finally:
        try:
            stream.stop()
        except Exception:
            log.debug("microphone stop raised", exc_info=True)
        try:
            stream.close()
        except Exception:
            log.debug("microphone close raised", exc_info=True)


def _run_perception_check(
    perception_check: Callable[..., Any] | None, config: dict[str, Any]
) -> list[Any]:
    if perception_check is None:
        from kaine.preboot import check_perception as perception_check

    if asyncio.iscoroutinefunction(perception_check):
        return asyncio.run(perception_check(config))
    return perception_check(config)


def _probe_seeded_video(
    perception_check: Callable[..., Any] | None, config: dict[str, Any]
) -> tuple[bool, str]:
    for row in _run_perception_check(perception_check, config):
        if "video" in row.name.lower() and row.status == "PASS":
            return True, ""
    for row in _run_perception_check(perception_check, config):
        if "video" in row.name.lower():
            return False, row.detail
    return False, "no video source check reported"


def _probe_seeded_audio(
    perception_check: Callable[..., Any] | None, config: dict[str, Any]
) -> tuple[bool, str]:
    for row in _run_perception_check(perception_check, config):
        if "audio" in row.name.lower() and row.status == "PASS":
            return True, ""
    for row in _run_perception_check(perception_check, config):
        if "audio" in row.name.lower():
            return False, row.detail
    return False, "no audio source check reported"


class InputLossWatcher:
    """Notify the caretaker when every watched input stream goes stale."""

    def __init__(
        self,
        bus: Any,
        streams: list[str],
        *,
        threshold_s: float,
        on_loss: Callable[[], Awaitable[None]],
        poll_s: float = 5.0,
    ) -> None:
        self._bus = bus
        self._streams = list(streams)
        self._threshold_ms = threshold_s * 1000
        self._on_loss = on_loss
        self._poll_s = poll_s
        self._lost = False
        self._start_ms = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll stream freshness until ``stop_event`` is set.

        Cancellation propagates out of this method; bus errors are logged
        and skipped for that poll only.
        """
        try:
            self._start_ms = await self._bus.server_time_ms()
        except Exception:
            log.warning(
                "InputLossWatcher: server_time_ms failed at start, using 0",
                exc_info=True,
            )
            self._start_ms = 0

        self._lost = False

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_s)
            except asyncio.TimeoutError:
                try:
                    now_ms = await self._bus.server_time_ms()
                except Exception:
                    log.warning(
                        "InputLossWatcher: server_time_ms failed, skipping poll",
                        exc_info=True,
                    )
                    continue
                await self._poll_once(now_ms)
            else:
                break

    async def _poll_once(self, now_ms: int) -> bool:
        """Evaluate freshness once and notify on a transition to lost.

        Returns ``True`` when input just became lost in this poll.
        """
        all_stale = True
        any_fresh = False
        bus_error = False

        for stream in self._streams:
            try:
                latest = await self._bus.latest(stream)
            except Exception:
                log.warning(
                    "InputLossWatcher: bus.latest(%r) failed, skipping poll",
                    stream,
                    exc_info=True,
                )
                bus_error = True
                continue

            if latest is None:
                last_ms = self._start_ms
            else:
                entry_id = latest[0]
                try:
                    id_ms = int(entry_id.split("-")[0])
                except Exception:
                    id_ms = 0
                last_ms = max(id_ms, self._start_ms)

            if now_ms - last_ms <= self._threshold_ms:
                all_stale = False
                any_fresh = True

        if bus_error:
            return False

        became_lost = False
        if all_stale and not self._lost:
            self._lost = True
            try:
                await self._on_loss()
            except Exception:
                log.exception("InputLossWatcher: on_loss callback failed")
            became_lost = True
        elif any_fresh and self._lost:
            self._lost = False

        return became_lost
