# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Eidolon factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.boot.errors import _pop, _require_keys
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule


def make_eidolon(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.eidolon.module import Eidolon
    from kaine.modules.eidolon.self_inference import SelfInferenceEngine

    allowed = {
        "persistence_path",
        "drift_window",
        "drift_threshold",
        "save_interval_s",
        "internal_speech_stream",
        "external_speech_stream",
        "identity_history_cap",
        "voice_observations_cap",
        "baseline_salience",
        "alert_salience",
        "self_inference",  # nested sub-table
    }
    kw = _pop(section, allowed)

    # Build the SelfInferenceEngine from the optional [eidolon.self_inference]
    # sub-table.  Ships disabled by default — operator must set enabled = true.
    si_section = kw.pop("self_inference", None) or {}
    si_allowed = {
        "enabled",
        "vad_window_cycles",
        "speech_pattern_min_count",
        "seed_path",
    }
    _require_keys(si_section, si_allowed)
    si_enabled = bool(si_section.get("enabled", False))
    si_kwargs: dict[str, Any] = {"enabled": si_enabled}
    if "vad_window_cycles" in si_section:
        si_kwargs["vad_window_cycles"] = int(si_section["vad_window_cycles"])
    if "speech_pattern_min_count" in si_section:
        si_kwargs["speech_pattern_min_count"] = int(si_section["speech_pattern_min_count"])
    if "seed_path" in si_section:
        seed_raw = str(si_section["seed_path"]).strip()
        if seed_raw:
            si_kwargs["seed_path"] = seed_raw
    inference_engine = SelfInferenceEngine(**si_kwargs)

    return Eidolon(bus, self_inference=inference_engine, **kw)
