# SPDX-License-Identifier: LicenseRef-CAL-0.2
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


def _topos_cv2_needed(config: dict) -> bool:
    if (config.get("topos") or {}).get("capture_enabled"):
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
        or mode in {"playlist", "seeded", "womb", "screen"}
    )
    if not live_path:
        return False
    backend = (config.get("audition") or {}).get("vad_backend", "webrtcvad")
    return backend != "rms"


def _audition_av_needed(config: dict) -> bool:
    return _perception_mode(config) == "playlist"


def _mnemos_qdrant(config: dict) -> bool:
    return (config.get("mnemos") or {}).get("backend", "qdrant") == "qdrant"


def _mnemos_sqlite_vec(config: dict) -> bool:
    return (config.get("mnemos") or {}).get("backend", "qdrant") in {
        "sqlite_vec",
        "sqlite-vec",
    }


def _empatheia_qdrant(config: dict) -> bool:
    return (config.get("empatheia") or {}).get("backend", "qdrant") == "qdrant"


def _hypnos_embedder_enabled(config: dict) -> bool:
    return (config.get("hypnos") or {}).get("consolidation_embedder_enabled", True)


def _phantasia_dreamerv3(config: dict) -> bool:
    return (config.get("phantasia") or {}).get("backend", "dreamerv3") == "dreamerv3"


#: Maps a module/service name to the requirements that must be satisfied when
#: it is enabled.  The keys are the public names used by the config table
#: ``[modules].<name>``; ``"nexus"`` is a service and is only checked when
#: explicitly requested.
REQUIREMENTS: dict[str, tuple[Requirement, ...]] = {
    "soma": (
        Requirement("torch", "core"),
        Requirement("ncps", "core"),
        Requirement("pynvml", "nvidia", severity="warning"),
    ),
    "chronos": (
        Requirement("torch", "core"),
        Requirement("ncps", "core"),
    ),
    "mnemos": (
        Requirement("sentence_transformers", "memory"),
        Requirement("qdrant_client", "memory", predicate=_mnemos_qdrant),
        Requirement("sqlite_vec", "memory-edge", predicate=_mnemos_sqlite_vec),
    ),
    "empatheia": (
        Requirement("qdrant_client", "memory", predicate=_empatheia_qdrant),
        Requirement("sentence_transformers", "memory", predicate=_empatheia_qdrant),
    ),
    "hypnos": (
        Requirement(
            "sentence_transformers",
            "memory",
            severity="warning",
            predicate=_hypnos_embedder_enabled,
        ),
    ),
    "topos": (
        Requirement("torch", "core"),
        Requirement("transformers", "vision"),
        Requirement("PIL", "vision"),
        Requirement("cv2", "vision", predicate=_topos_cv2_needed),
    ),
    "audition": (
        Requirement("sounddevice", "audio", predicate=_audition_sounddevice_needed),
        Requirement("webrtcvad", "audio", predicate=_audition_webrtcvad_needed),
        Requirement("av", "audio", predicate=_audition_av_needed),
    ),
    "nous": (
        Requirement("pymdp", "reasoning"),
        Requirement("jax", "reasoning"),
    ),
    "phantasia": (
        Requirement("jax", "worldmodel", predicate=_phantasia_dreamerv3),
    ),
    "nexus": (
        Requirement("fastapi", "nexus"),
        Requirement("uvicorn", "nexus"),
        Requirement("jinja2", "nexus", transitive_for="fastapi.templating"),
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
        if name == "nexus":
            if "nexus" not in enabled_services:
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
