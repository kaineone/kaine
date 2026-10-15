# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The vision module factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.config_kwargs import config_kwargs
from kaine.boot.errors import _require_keys
from kaine.boot.perception_feed import _build_perception_feed_video_factory
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.positive_control import PositiveControlSettings


def make_vision(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.vision.live import LiveCameraConfig
    from kaine.modules.vision.module import Vision

    allowed = {
        # Encoder selection (topos-temporal-video-encoder). encoder_backend
        # picks InternVideo-Next (the shipped default clip encoder) or DINOv2
        # (the per-frame fallback). encoder_revision/encoder_local_dir pin and
        # locate the vendored InternVideo-Next weights; DINOv2 does not use them.
        "encoder_backend",
        "encoder_model_id",
        "encoder_revision",
        "encoder_local_dir",
        # InternVideo-Next clip seam (topos-temporal-video-encoder): clip length,
        # strided-clip cadence, input resolution, and token pooling. Ignored by
        # the DINOv2 fallback (clip_len is fixed at 1 there).
        "clip_len",
        "clip_stride",
        "clip_resolution",
        "pooling",
        "device",
        "change_alert_threshold",
        "change_alert_factor",
        "habituation_window",  # consumed by habituator default
        "baseline_salience",
        "alert_salience",
        # Live camera (eyes-only). Off by default.
        "capture_enabled",
        "capture_device",
        "capture_interval_s",
        # Subjective vision-sampling rate (Hz). The clean, biological expression
        # of the capture cadence (1 / capture_interval_s), decoupled from the
        # workspace tick. If set it takes precedence over capture_interval_s.
        # Shipped as 10.0 Hz in config/kaine.toml (benchmarked-cleared,
        # operator-approved); when absent the class default of 1.0 Hz holds.
        "vision_sample_hz",
        "capture_width",
        "capture_height",
        "capture_warmup_frames",
        # Forward prediction (disabled by default).
        "forward_prediction",
        "forward_model_units",
        "prediction_error_window",
        "visual_buffer_size",
        # Attention-driven foveation (vision-foveation). Off by default → the
        # single whole-frame encode is unchanged. See make_vision foveation block.
        "foveation",
        "foveation_grid",
        "foveation_hysteresis",
        "foveation_arousal_size_min",
        "foveation_arousal_size_max",
        "peripheral_width",
        "peripheral_height",
        "foveal_size",
        # Unified deterministic perception feed (unified-perception-feed). This
        # is the resolved top-level [perception_feed] config, injected by
        # build_registry under this reserved key (NOT a [vision.*] key the
        # operator sets). Selecting a seeded/playlist mode supplies a
        # source_factory and forces capture on. Shipped mode = "off". Popped
        # before the key check below.
        "perception_feed",
    }
    feed_section = dict(section.pop("perception_feed", {}) or {})
    pc_section = section.pop("positive_control", None)
    _require_keys(section, allowed - {"perception_feed"})
    kwargs: dict[str, Any] = {}
    kwargs["positive_control"] = PositiveControlSettings.from_config(pc_section)
    if "encoder_backend" in section:
        kwargs["encoder_backend"] = section["encoder_backend"]
    if "encoder_model_id" in section:
        kwargs["encoder_model_id"] = section["encoder_model_id"]
    if "encoder_local_dir" in section:
        kwargs["encoder_weights_dir"] = section["encoder_local_dir"]
    # InternVideo-Next clip seam knobs (topos-temporal-video-encoder). clip_len
    # and clip_resolution/pooling configure the clip encoder; clip_stride is the
    # vision-module-level strided-clip cadence.
    if "clip_len" in section:
        kwargs["encoder_clip_len"] = int(section["clip_len"])
    if "clip_resolution" in section:
        kwargs["encoder_clip_resolution"] = int(section["clip_resolution"])
    if "pooling" in section:
        kwargs["encoder_pooling"] = str(section["pooling"])
    if "clip_stride" in section:
        kwargs["clip_stride"] = int(section["clip_stride"])
    if "encoder_revision" in section:
        from kaine.modules.vision.internvideo_next_loader import PINNED_REVISION

        configured = str(section["encoder_revision"]).strip()
        if configured != PINNED_REVISION:
            raise ValueError(
                f"[vision].encoder_revision {configured!r} does not match the pinned "
                f"InternVideo-Next revision {PINNED_REVISION!r}; the pin decides which "
                f"vendored code and weights load, so it cannot be changed from configuration"
            )
    if "device" in section:
        kwargs["device_preference"] = section["device"]
    kwargs.update(
        config_kwargs(
            section,
            (
                "change_alert_threshold",
                "change_alert_factor",
                "baseline_salience",
                "alert_salience",
            ),
            Vision,
        )
    )
    if "habituation_window" in section:
        from kaine.modules.vision.habituation import RollingMeanHabituator

        window = section["habituation_window"]
        if not isinstance(window, int) or isinstance(window, bool) or window < 2:
            raise ValueError(
                "[vision].habituation_window must be an integer of at least 2"
            )
        kwargs["habituator"] = RollingMeanHabituator(window=window)
    # Forward prediction knobs
    kwargs.update(
        config_kwargs(
            section,
            (
                "forward_prediction",
                "forward_model_units",
                "prediction_error_window",
                "visual_buffer_size",
            ),
            Vision,
        )
    )
    kwargs["capture_enabled"] = bool(section.get("capture_enabled", False))

    # Attention-driven foveation (vision-foveation). Off by default → the vision module runs
    # the single whole-frame encode. When on, each frame yields a spatial saliency
    # map, one arousal-sized fovea, and a peripheral + foveal encode. The grab is
    # native by default — for screen mode set capture_width/height to the panel
    # resolution (the host benchmark can dial it back). See openspec vision-foveation.
    if bool(section.get("foveation", False)):
        kwargs["foveation_enabled"] = True
        grid = section.get("foveation_grid")
        if grid is not None:
            kwargs["foveation_grid"] = (int(grid[0]), int(grid[1]))
        if "foveation_hysteresis" in section:
            kwargs["foveation_hysteresis"] = float(section["foveation_hysteresis"])
        size_min = section.get("foveation_arousal_size_min")
        size_max = section.get("foveation_arousal_size_max")
        if size_min is not None or size_max is not None:
            lo = float(size_min if size_min is not None else 0.12)
            hi = float(size_max if size_max is not None else 0.5)
            kwargs["foveation_size_range"] = (lo, hi)
        pw = section.get("peripheral_width")
        ph = section.get("peripheral_height")
        if pw is not None or ph is not None:
            kwargs["peripheral_size"] = (
                int(pw if pw is not None else 320),
                int(ph if ph is not None else 180),
            )
        if "foveal_size" in section:
            fs = int(section["foveal_size"])
            kwargs["foveal_size"] = (fs, fs)

    # Unified deterministic perception feed selection (unified-perception-feed).
    # mode "off"/"live" leave the existing behaviour (off = capture disabled;
    # live = the real cv2 camera + real mic path). "seeded"/"playlist" supply a
    # source_factory and force capture on so LiveCamera reads from the
    # deterministic source.
    mode = str(feed_section.get("mode", "off")).lower()
    if mode not in ("off", "seeded", "playlist", "stimulus_source", "live", "screen"):
        raise ValueError(
            f"[perception_feed].mode must be off/seeded/playlist/stimulus_source/live/screen, got {mode!r}"
        )
    width = int(section.get("capture_width", 640))
    height = int(section.get("capture_height", 480))
    if mode == "live":
        # Real camera path: honour the existing live-camera config below.
        kwargs["capture_enabled"] = True
    elif mode in ("seeded", "playlist", "stimulus_source", "screen"):
        kwargs["source_factory"] = _build_perception_feed_video_factory(
            mode, feed_section, width=width, height=height
        )
        kwargs["capture_enabled"] = True

    if kwargs["capture_enabled"]:
        # Vision sampling is a subjective rate decoupled from the workspace tick.
        # Accept either capture_interval_s (subjective seconds/frame) or the
        # cleaner vision_sample_hz (frames/subjective second); the rate wins when
        # both are present. The shipped config sets vision_sample_hz = 10.0
        # (benchmark-cleared, operator-approved); when neither key is present the
        # class default of 1.0 s (1 Hz) holds.
        if "vision_sample_hz" in section:
            capture_interval_s = LiveCameraConfig.interval_from_hz(
                float(section["vision_sample_hz"])
            )
        else:
            capture_interval_s = float(section.get("capture_interval_s", 1.0))
        kwargs["live_camera_config"] = LiveCameraConfig(
            device=section.get("capture_device", 0),
            capture_interval_s=capture_interval_s,
            width=width,
            height=height,
            warmup_frames=int(section.get("capture_warmup_frames", 3)),
        )
    return Vision(bus, entity_clock=entity_clock, **kwargs)
