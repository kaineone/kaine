# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A fork's optional subjective-time profile (Phase 4 of biological timing).

A forked being may carry its own ``time_scale`` (and optional per-rate
overrides) so it runs at its own subjective speed once restored to run. The
profile lives in the **existing** free ``ForkSnapshot.metadata`` dict under a
``timing`` key — no new storage, no new fork/merge machinery:

    metadata["timing"] = {
        "time_scale": 2.0,            # required if the key is present; > 0
        "processing_rate_hz": 10.0,   # optional override (else inherit current)
        "experiential_rate_hz": 3.333,
        "vision_sample_hz": 10.0,
    }

This module is the **typed parse/validate boundary**: callers go through
``fork_timing_profile`` and never poke the raw dict, so an invalid value
(``time_scale <= 0`` for a runnable fork, a non-numeric rate) fails loudly here
rather than silently mis-pacing a being. ``time_scale == 0`` is the existing
freeze path (``control_state.py``), not a runnable profile, so it is rejected.

Boundary-neutral: this module imports nothing from ``kaine.cycle``,
``kaine.modules``, or ``kaine.entity_clock`` — it is pure data + validation, so
it can sit next to ``ForkSnapshot`` in the lifecycle layer without dragging in
the runtime. The runtime *apply* seam (which DOES touch the clock and the cycle)
lives in ``kaine.cycle.fork_timing`` and consumes a ``ForkTimingProfile``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

# The metadata sub-dict key under which a fork carries its timing profile.
TIMING_METADATA_KEY = "timing"


class InvalidForkTimingProfile(ValueError):
    """Raised when a fork's ``metadata['timing']`` is present but malformed.

    A loud failure at parse time is deliberate: a silently-dropped or
    mis-coerced ``time_scale`` would mis-pace a being. Callers that attach a
    profile (the ``POST /forks`` API) and callers that apply one (the runtime
    seam) both surface this rather than guessing.
    """


def _coerce_positive(value: Any, field: str) -> float:
    """Coerce ``value`` to a strictly-positive float or raise loudly."""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidForkTimingProfile(
            f"timing.{field} must be a number, got {value!r}"
        ) from exc
    if math.isnan(out):
        raise InvalidForkTimingProfile(f"timing.{field} must be a number, got NaN")
    if out <= 0:
        raise InvalidForkTimingProfile(
            f"timing.{field} must be > 0, got {out!r}"
        )
    return out


@dataclass(frozen=True)
class ForkTimingProfile:
    """A validated, runnable subjective-time profile for a fork.

    ``time_scale`` is the only required field (and is always ``> 0`` — a
    runnable being is never frozen via a timing profile). The rate overrides are
    optional; when absent the fork inherits the prevailing cycle / perception
    rates at spawn.
    """

    time_scale: float
    processing_rate_hz: float | None = None
    experiential_rate_hz: float | None = None
    vision_sample_hz: float | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Render this profile back to the ``metadata['timing']`` sub-dict.

        Only the populated keys are emitted, so a profile with just a
        ``time_scale`` round-trips to ``{"time_scale": ...}`` (no null rates).
        """
        out: dict[str, Any] = {"time_scale": self.time_scale}
        if self.processing_rate_hz is not None:
            out["processing_rate_hz"] = self.processing_rate_hz
        if self.experiential_rate_hz is not None:
            out["experiential_rate_hz"] = self.experiential_rate_hz
        if self.vision_sample_hz is not None:
            out["vision_sample_hz"] = self.vision_sample_hz
        return out


def build_timing_metadata(
    *,
    time_scale: float | None = None,
    processing_rate_hz: float | None = None,
    experiential_rate_hz: float | None = None,
    vision_sample_hz: float | None = None,
) -> dict[str, Any]:
    """Pack provided timing fields into a ``{"timing": {...}}`` metadata dict.

    Only the keys actually supplied are included (so an operator who passes just
    a ``time_scale`` does not pin the rates). Returns an empty dict when nothing
    is provided, so the caller can ``{**metadata, **build_timing_metadata(...)}``
    without conditionals and a profile-less fork carries no ``timing`` key (and
    therefore stays behavior-preserving). Validates eagerly so a bad value is
    rejected at the API boundary, not silently stored.
    """
    timing: dict[str, Any] = {}
    if time_scale is not None:
        timing["time_scale"] = _coerce_positive(time_scale, "time_scale")
    if processing_rate_hz is not None:
        timing["processing_rate_hz"] = _coerce_positive(
            processing_rate_hz, "processing_rate_hz"
        )
    if experiential_rate_hz is not None:
        timing["experiential_rate_hz"] = _coerce_positive(
            experiential_rate_hz, "experiential_rate_hz"
        )
    if vision_sample_hz is not None:
        timing["vision_sample_hz"] = _coerce_positive(
            vision_sample_hz, "vision_sample_hz"
        )
    # A rate override without a time_scale is not a runnable profile (time_scale
    # is the required anchor). Reject it loudly rather than store a half-profile
    # the apply seam would later treat as absent.
    if timing and "time_scale" not in timing:
        raise InvalidForkTimingProfile(
            "timing rate override(s) provided without a time_scale; "
            "a runnable profile requires time_scale > 0"
        )
    return {TIMING_METADATA_KEY: timing} if timing else {}


def fork_timing_profile(
    source: Mapping[str, Any] | Any,
) -> ForkTimingProfile | None:
    """Parse + validate a fork's timing profile from a snapshot or metadata.

    ``source`` may be a ``ForkSnapshot`` (anything exposing a ``.metadata``
    mapping) or the raw metadata mapping itself. Returns:

    - ``None`` when there is no ``timing`` key (or it is an empty dict) — the
      behavior-preserving default; the fork runs at the prevailing scale/rates.
    - a validated :class:`ForkTimingProfile` when ``timing.time_scale > 0`` is
      present, with any optional rate overrides validated too.

    Raises :class:`InvalidForkTimingProfile` when ``timing`` is present but
    malformed (missing/``<= 0``/non-numeric ``time_scale``, or a non-positive
    rate override) — a loud failure beats silently mis-pacing a being.
    """
    metadata = getattr(source, "metadata", source)
    if not isinstance(metadata, Mapping):
        raise InvalidForkTimingProfile(
            f"expected a snapshot or metadata mapping, got {type(source).__name__}"
        )
    raw = metadata.get(TIMING_METADATA_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise InvalidForkTimingProfile(
            f"metadata['{TIMING_METADATA_KEY}'] must be a mapping, got {raw!r}"
        )
    if not raw:
        # An explicitly empty timing dict carries no profile — treat as absent.
        return None
    if "time_scale" not in raw:
        raise InvalidForkTimingProfile(
            f"metadata['{TIMING_METADATA_KEY}'] is present but has no "
            f"'time_scale'; a runnable profile requires time_scale > 0 "
            f"(time_scale == 0 is the freeze path, not a timing profile)"
        )
    time_scale = _coerce_positive(raw["time_scale"], "time_scale")
    processing = raw.get("processing_rate_hz")
    experiential = raw.get("experiential_rate_hz")
    vision = raw.get("vision_sample_hz")
    return ForkTimingProfile(
        time_scale=time_scale,
        processing_rate_hz=(
            _coerce_positive(processing, "processing_rate_hz")
            if processing is not None
            else None
        ),
        experiential_rate_hz=(
            _coerce_positive(experiential, "experiential_rate_hz")
            if experiential is not None
            else None
        ),
        vision_sample_hz=(
            _coerce_positive(vision, "vision_sample_hz")
            if vision is not None
            else None
        ),
    )
