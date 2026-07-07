# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operational state for KAINE's live perception streams.

Two files under `state/perception/`:

  runtime.json — written by the perception tasks (LiveMicrophone,
                 LiveCamera) on every start/stop. Source of truth for
                 the Nexus on-air banner.

  desired.json — written by the Nexus POST /diagnostics/perception/toggle
                 endpoint. Operator's commanded state. Perception tasks
                 poll it and start/stop themselves to match.

Both files contain ONLY operational booleans + ISO timestamps. NEVER any
sensory content (no transcribed text, no audio bytes, no frame data).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.state_io import write_json_atomic

RUNTIME_PATH = Path("state/perception/runtime.json")
DESIRED_PATH = Path("state/perception/desired.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# The entity's perceptual locus — which world its organs (Topos vision,
# Audio-In hearing) bind to. Exactly one at a time:
#   physical — real camera + mic (the room)
#   virtual  — the embodied avatar (in-world feeds); real camera/mic OFF
#   off      — no perception
# This mutual exclusion is load-bearing for privacy: the real camera/mic are
# never on while the entity is "away" in the virtual world.
LOCI = ("physical", "virtual", "off")


def _coerce_locus(value: Any) -> str:
    return value if value in LOCI else "physical"


@dataclass(frozen=True)
class PerceptionState:
    audio_live_active: bool = False
    video_live_active: bool = False
    audio_last_started_at: str | None = None
    video_last_started_at: str | None = None
    audio_last_stopped_at: str | None = None
    video_last_stopped_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PerceptionState":
        data = dict(data or {})
        return cls(
            audio_live_active=bool(data.get("audio_live_active", False)),
            video_live_active=bool(data.get("video_live_active", False)),
            audio_last_started_at=data.get("audio_last_started_at"),
            video_last_started_at=data.get("video_last_started_at"),
            audio_last_stopped_at=data.get("audio_last_stopped_at"),
            video_last_stopped_at=data.get("video_last_stopped_at"),
        )


@dataclass(frozen=True)
class DesiredState:
    audio_live_desired: bool = False
    video_live_desired: bool = False
    # Perceptual locus (see LOCI). The real camera/mic can only run in
    # `physical`; `virtual`/`off` force them off regardless of the audio/video
    # desired flags. `locus_locked` prevents the entity from self-switching.
    locus: str = "physical"
    locus_locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DesiredState":
        data = dict(data or {})
        return cls(
            audio_live_desired=bool(data.get("audio_live_desired", False)),
            video_live_desired=bool(data.get("video_live_desired", False)),
            locus=_coerce_locus(data.get("locus", "physical")),
            locus_locked=bool(data.get("locus_locked", False)),
        )


# Shared boundary-neutral atomic JSON writer (see kaine.state_io).
_atomic_write = write_json_atomic


def read_runtime(path: Path | None = None) -> PerceptionState:
    target = path or RUNTIME_PATH
    if not target.exists():
        return PerceptionState()
    try:
        return PerceptionState.from_dict(json.loads(target.read_text()))
    except (json.JSONDecodeError, OSError):
        return PerceptionState()


def write_runtime(state: PerceptionState, path: Path | None = None) -> None:
    _atomic_write(path or RUNTIME_PATH, state.to_dict())


def update_audio_runtime(
    active: bool, path: Path | None = None
) -> PerceptionState:
    cur = read_runtime(path)
    now = _now_iso()
    updated = replace(
        cur,
        audio_live_active=active,
        audio_last_started_at=now if active else cur.audio_last_started_at,
        audio_last_stopped_at=now if not active else cur.audio_last_stopped_at,
    )
    write_runtime(updated, path)
    return updated


def update_video_runtime(
    active: bool, path: Path | None = None
) -> PerceptionState:
    cur = read_runtime(path)
    now = _now_iso()
    updated = replace(
        cur,
        video_live_active=active,
        video_last_started_at=now if active else cur.video_last_started_at,
        video_last_stopped_at=now if not active else cur.video_last_stopped_at,
    )
    write_runtime(updated, path)
    return updated


def read_desired(path: Path | None = None) -> DesiredState:
    target = path or DESIRED_PATH
    if not target.exists():
        return DesiredState()
    try:
        return DesiredState.from_dict(json.loads(target.read_text()))
    except (json.JSONDecodeError, OSError):
        return DesiredState()


def write_desired_audio(active: bool, path: Path | None = None) -> DesiredState:
    cur = read_desired(path)
    updated = replace(cur, audio_live_desired=bool(active))
    _atomic_write(path or DESIRED_PATH, updated.to_dict())
    return updated


def write_desired_video(active: bool, path: Path | None = None) -> DesiredState:
    cur = read_desired(path)
    updated = replace(cur, video_live_desired=bool(active))
    _atomic_write(path or DESIRED_PATH, updated.to_dict())
    return updated


def write_desired_locus(
    locus: str, locked: bool | None = None, path: Path | None = None
) -> DesiredState:
    """Set the perceptual locus (and optionally its lock). Invalid values fall
    back to `physical` so the camera/mic can never be left in an unknown state."""
    cur = read_desired(path)
    updated = replace(
        cur,
        locus=_coerce_locus(locus),
        locus_locked=cur.locus_locked if locked is None else bool(locked),
    )
    _atomic_write(path or DESIRED_PATH, updated.to_dict())
    return updated


def effective_audio_capture(path: Path | None = None) -> bool:
    """Whether the REAL microphone should run: only when the operator/entity
    wants audio AND the locus is `physical`."""
    d = read_desired(path)
    return d.audio_live_desired and d.locus == "physical"


def effective_video_capture(path: Path | None = None) -> bool:
    """Whether the REAL camera should run: only when video is wanted AND the
    locus is `physical`. `virtual`/`off` keep the camera dark."""
    d = read_desired(path)
    return d.video_live_desired and d.locus == "physical"


def effective_virtual_audio_capture(path: Path | None = None) -> bool:
    """Whether the VIRTUAL audio feed (the seeded/playlist deterministic source)
    should run: only when audio is wanted AND the locus is `virtual`.

    Mirror of ``effective_audio_capture`` for the other side of the physical-XOR-
    virtual locus model: the deterministic feed IS the virtual world, so it binds
    to `virtual` exactly as the real mic binds to `physical`. The shared
    ``audio_live_desired`` flag still gates it (so the operator mute toggle works
    on the virtual feed too)."""
    d = read_desired(path)
    return d.audio_live_desired and d.locus == "virtual"


def effective_virtual_video_capture(path: Path | None = None) -> bool:
    """Whether the VIRTUAL video feed (the seeded/playlist deterministic source)
    should run: only when video is wanted AND the locus is `virtual`. The real
    camera path uses ``effective_video_capture`` (`physical`); this is its
    virtual-locus mirror."""
    d = read_desired(path)
    return d.video_live_desired and d.locus == "virtual"


def select_virtual_feed(path: Path | None = None) -> DesiredState:
    """Rez into the VIRTUAL locus with both modalities perceiving — the boot
    default when a deterministic perception feed (seeded/playlist) is configured.

    A configured feed IS the entity's world, so booting with one selected must
    actually bind the senses to it. This translates ``[perception_feed].mode =
    seeded|playlist`` (the only knob the operator sets) into the runtime desired-
    state the locus-gated capture supervisors read. The operator can still mute
    either modality or switch locus afterward via Nexus.

    Honours the operator lock: if ``locus_locked`` is set, the locus is left
    untouched (the operator's explicit lock wins over the configured feed) and
    the unchanged state is returned so the caller can warn."""
    cur = read_desired(path)
    if cur.locus_locked:
        return cur
    updated = replace(
        cur,
        locus="virtual",
        audio_live_desired=True,
        video_live_desired=True,
    )
    _atomic_write(path or DESIRED_PATH, updated.to_dict())
    return updated


def evaluate_locus_switch(
    requested: str,
    *,
    current: str,
    locked: bool,
    allow_self_switch: bool,
    inhibited: bool,
    since_last_switch_s: float,
    min_dwell_s: float,
) -> tuple[bool, str]:
    """Decide whether an ENTITY-initiated locus switch is allowed.

    Operator switches (via Nexus) bypass this — it gates only self-initiated
    `intent.perception.switch`. Returns (allowed, reason).
    """
    if requested not in LOCI:
        return False, "invalid locus"
    if requested == current:
        return False, "already in that locus"
    if locked:
        return False, "locus locked by operator"
    if not allow_self_switch:
        return False, "self-switch disabled by policy"
    if inhibited:
        return False, "inhibited"
    if since_last_switch_s < min_dwell_s:
        return False, "minimum dwell time not elapsed"
    return True, "ok"


def reset_for_tests(path_runtime: Path | None = None, path_desired: Path | None = None) -> None:
    for target in (path_runtime or RUNTIME_PATH, path_desired or DESIRED_PATH):
        if target.exists():
            try:
                target.unlink()
            except OSError:
                # Test-helper cleanup only: another test/process may have
                # already removed the file between the exists() check and
                # unlink() — the end state (file gone) is what we want anyway.
                pass
