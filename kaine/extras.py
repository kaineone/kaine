# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dependency-extra requirement table and fail-closed check for KAINE.

This module uses only the Python standard library so it can be imported on a
lean host without pulling any heavy optional dependency.  It records which
extra provides which import for every module/service and checks a config
against the installed environment before any module is constructed.
"""
from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Requirement:
    """A single import an enabled module/service needs and the extra that
    provides it."""

    import_name: str
    extra: str
    severity: str = "error"
    predicate: Optional[Callable[[dict], bool]] = None
    # Some rows describe a dependency that is installed only because a
    # direct dependency needs it (e.g. jinja2 for fastapi.templating).  The
    # codebase imports the direct dependency, not the transitive one, so
    # import-scan tests skip rows that set this field.
    transitive_for: Optional[str] = None

    def applies(self, config: dict) -> bool:
        return True if self.predicate is None else bool(self.predicate(config))


@dataclass(frozen=True)
class Missing:
    """A requirement that is not satisfied in the current environment."""

    module: str
    import_name: str
    extra: str
    severity: str


def _perception_mode(config: dict) -> str | None:
    return (config.get("perception_feed") or {}).get("mode")


def _vision_cv2_needed(config: dict) -> bool:
    if (config.get("vision") or {}).get("capture_enabled"):
        return True
    return _perception_mode(config) == "playlist"


def _audition_sounddevice_needed(config: dict) -> bool:
    """sounddevice is only used when audition itself opens a real mic device."""
    if not (config.get("audition") or {}).get("capture_enabled"):
        return False
    mode = _perception_mode(config)
    # Feed modes provide an explicit stream factory, so a real device is only
    # needed for the unset/default path, an explicit "live" device, or "off"
    # (i.e. no feed, direct capture).
    return mode in (None, "live", "off")


def _audition_webrtcvad_needed(config: dict) -> bool:
    """webrtcvad runs on the live-microphone path unless the RMS fallback is
    selected."""
    mode = _perception_mode(config)
    live_path = (
        (config.get("audition") or {}).get("capture_enabled")
        or mode in {"playlist", "seeded", "stimulus_source", "screen"}
    )
    if not live_path:
        return False
    backend = (config.get("audition") or {}).get("vad_backend", "webrtcvad")
    return backend != "rms"


def _audition_av_needed(config: dict) -> bool:
    return _perception_mode(config) == "playlist"


def _audition_sherpa(config: dict) -> bool:
    section = config.get("audition") or {}
    backend = str(section.get("backend") or "speaches").strip().lower()
    return backend == "sherpa_onnx" and bool(section.get("transcription_enabled", False))


def _vocal_sherpa(config: dict) -> bool:
    section = config.get("vocal") or {}
    backend = str(section.get("backend") or "chatterbox").strip().lower()
    return backend == "sherpa_onnx"


def _episodic_memory_qdrant(config: dict) -> bool:
    return (config.get("episodic_memory") or {}).get("backend", "qdrant") == "qdrant"


def _episodic_memory_sqlite_vec(config: dict) -> bool:
    return (config.get("episodic_memory") or {}).get("backend", "qdrant") in {
        "sqlite_vec",
        "sqlite-vec",
    }


def _social_cognition_qdrant(config: dict) -> bool:
    return (config.get("social_cognition") or {}).get("backend", "qdrant") == "qdrant"


def _sleep_embedder_enabled(config: dict) -> bool:
    return (config.get("sleep") or {}).get("consolidation_embedder_enabled", True)


def _embedding_torch_backend(config: dict) -> bool:
    from kaine.text_embedding import resolve_embedding_config
    return resolve_embedding_config(config)["backend"] == "sentence_transformers"


def _world_model_jax_engine(config: dict) -> bool:
    world_model = config.get("world_model") or {}
    return (
        world_model.get("backend", "dreamerv3") == "dreamerv3"
        and world_model.get("engine", "jax") == "jax"
    )


def _interoception_torch_needed(config: dict) -> bool:
    return (config.get("interoception") or {}).get("cfc_backend", "numpy") == "torch"


def _sequence_torch_needed(config: dict) -> bool:
    return (config.get("sequence") or {}).get("cfc_backend", "numpy") == "torch"


def _planning_pymdp_backend(config: dict) -> bool:
    return (config.get("planning") or {}).get("backend", "pymdp") == "pymdp"


#: Maps a module/service name to the requirements that must be satisfied when
#: it is enabled.  The keys are the public names used by the config table
#: ``[modules].<name>``; ``"dashboard"`` is a service and is only checked when
#: explicitly requested.
REQUIREMENTS: dict[str, tuple[Requirement, ...]] = {
    "interoception": (
        Requirement("torch", "core", predicate=_interoception_torch_needed),
        Requirement("ncps", "core", predicate=_interoception_torch_needed),
        Requirement("pynvml", "nvidia", severity="warning"),
    ),
    "sequence": (
        Requirement("torch", "core", predicate=_sequence_torch_needed),
        Requirement("ncps", "core", predicate=_sequence_torch_needed),
    ),
    "episodic_memory": (
        Requirement("sentence_transformers", "memory", predicate=_embedding_torch_backend),
        Requirement("qdrant_client", "memory", predicate=_episodic_memory_qdrant),
        Requirement("sqlite_vec", "memory-edge", predicate=_episodic_memory_sqlite_vec),
    ),
    "social_cognition": (
        Requirement("qdrant_client", "memory", predicate=_social_cognition_qdrant),
        Requirement(
            "sentence_transformers",
            "memory",
            predicate=lambda c: _social_cognition_qdrant(c) and _embedding_torch_backend(c),
        ),
    ),
    "sleep": (
        Requirement(
            "sentence_transformers",
            "memory",
            severity="warning",
            predicate=lambda c: _sleep_embedder_enabled(c) and _embedding_torch_backend(c),
        ),
    ),
    "vision": (
        Requirement("torch", "core"),
        Requirement("transformers", "vision"),
        Requirement("PIL", "vision"),
        Requirement("cv2", "vision", predicate=_vision_cv2_needed),
    ),
    "audition": (
        Requirement("sounddevice", "audio", predicate=_audition_sounddevice_needed),
        Requirement("webrtcvad", "audio", predicate=_audition_webrtcvad_needed),
        Requirement("av", "audio", predicate=_audition_av_needed),
        Requirement("sherpa_onnx", "speech-edge", predicate=_audition_sherpa),
    ),
    "vocal": (
        Requirement("sherpa_onnx", "speech-edge", predicate=_vocal_sherpa),
    ),
    "planning": (
        Requirement("pymdp", "reasoning", predicate=_planning_pymdp_backend),
        Requirement("jax", "reasoning", predicate=_planning_pymdp_backend),
    ),
    "world_model": (
        Requirement("jax", "worldmodel", predicate=_world_model_jax_engine),
    ),
    "dashboard": (
        Requirement("fastapi", "dashboard"),
        Requirement("uvicorn", "dashboard"),
        Requirement("jinja2", "dashboard", transitive_for="fastapi.templating"),
    ),
}


def check(config: dict, *, services: Optional[Iterable[str]] = None) -> list[Missing]:
    """Return every unsatisfied requirement for the enabled modules/services.

    Uses :func:`importlib.util.find_spec` so nothing heavy is imported.  The
    returned list contains both hard errors and warnings; callers decide how
    to report each severity.
    """
    toggles = config.get("modules") or {}
    enabled_modules = {name for name, on in toggles.items() if on}
    enabled_services = set(services or ())

    missing: list[Missing] = []
    for name, reqs in REQUIREMENTS.items():
        if name == "dashboard":
            if "dashboard" not in enabled_services:
                continue
        elif name not in enabled_modules:
            continue

        for req in reqs:
            if not req.applies(config):
                continue
            if importlib.util.find_spec(req.import_name) is None:
                missing.append(
                    Missing(name, req.import_name, req.extra, req.severity)
                )

    return missing


def _error_missing(missing: list[Missing]) -> list[Missing]:
    return [m for m in missing if m.severity == "error"]


def format_missing(missing: list[Missing], *, package: str = "kaine") -> str:
    """Format the error-level missing requirements into one human-readable
    message that names each missing import and the install command that fixes
    it.  Warnings are intentionally omitted because they do not stop boot.
    """
    errors = _error_missing(missing)
    if not errors:
        return ""

    extras = sorted({m.extra for m in errors})
    lines = ["Missing optional dependencies for enabled modules/services:"]
    for m in errors:
        lines.append(
            f"  - {m.module} requires {m.import_name!r} "
            f"(extra: {m.extra})"
        )
    lines.append(f'  pip install "{package}[{",".join(extras)}]"')
    return "\n".join(lines)
