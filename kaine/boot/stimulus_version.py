# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The developmental stimulus version: one digest of what the developing entity hears and when.

A validation record about the developmental stimulus (the band-step record, the
live-gap record) is evidence only for the stimulus it measured. The version is
the sha256 of a canonical record of everything that decides the stimulus audio
and its hearing schedule: the stimulus-source parameters with the hearing
schedule, the maternal voice's parameters and manifest digest, the added sounds'
parameters and manifest digest, and the affect module's learning-progress floor,
span and bin, which decide when a hearing stage is released. A record names the
version it measured, and ``tests/test_band_step_records.py`` checks that records
exist for the shipped version.

Reading only: no file is written.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ("STIMULUS_VERSION_FORMAT", "developmental_stimulus_record", "developmental_stimulus_version")

STIMULUS_VERSION_FORMAT = "developmental-stimulus/1"


def _file_sha256(path) -> str:  # noqa: ANN001
    return hashlib.sha256(path.read_bytes()).hexdigest()


def developmental_stimulus_record(kaine_config: dict[str, Any]) -> dict[str, Any]:
    """The canonical record the version digests, from a parsed ``kaine.toml``.

    Raises ``ValueError`` for an invalid stimulus table, as boot would.
    """
    from kaine.boot.perception_feed import (
        _AFFECT_LP_SPAN_DEFAULT_S,
        _added_sounds_params,
        _hearing_band_params,
        _maternal_voice_params,
        _stimulus_source_params,
    )
    from kaine.lifecycle.stored_field_names import stimulus_source_params_record
    from kaine.modules.audition.added_sounds import ADDED_SOUNDS_DATA_DIR
    from kaine.modules.audition.maternal_voice import VOICE_DATA_DIR

    feed = dict(kaine_config.get("perception_feed") or {})
    affect = kaine_config.get("affect") or {}
    voice = _maternal_voice_params(feed)
    added = _added_sounds_params(feed)
    return {
        "format": STIMULUS_VERSION_FORMAT,
        "stimulus_source": stimulus_source_params_record(
            _stimulus_source_params(feed), hearing=_hearing_band_params(feed)
        ),
        "hearing_enabled": _hearing_band_params(feed).enabled,
        "audio_sample_rate": int((feed.get("audio") or {}).get("sample_rate", 16000)),
        "maternal_voice": {
            **voice.as_record(),
            "manifest_sha256": _file_sha256(VOICE_DATA_DIR / "manifest.json") if voice.enabled else None,
        },
        "added_sounds": {
            **added.as_record(),
            "manifest_sha256": _file_sha256(ADDED_SOUNDS_DATA_DIR / "manifest.json") if added.enabled else None,
        },
        "release_rule": {
            "learning_progress_floor": float(affect.get("learning_progress_floor", 0.20)),
            "learning_progress_span_s": float(affect.get("learning_progress_span_s", _AFFECT_LP_SPAN_DEFAULT_S)),
            "learning_progress_bin_s": float(affect.get("learning_progress_bin_s", 60.0)),
            "saturation": "full_span",
        },
    }


def developmental_stimulus_version(kaine_config: dict[str, Any]) -> str:
    """The sha256 hex digest of ``developmental_stimulus_record``."""
    payload = json.dumps(developmental_stimulus_record(kaine_config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
