# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kaine.state_io import write_json_atomic


@dataclass(frozen=True)
class FootprintEntry:
    """A single calibrated or observed footprint record."""

    component: str
    backend: str
    model_id: str
    peak_bytes: int
    device_peak_bytes: int | None
    weights_mapped: bool | None
    host_class: str
    measured_at: str
    kaine_version: str
    source: str

    def __post_init__(self) -> None:
        """Validate field types and values when constructed directly."""
        raw = {
            "component": self.component,
            "backend": self.backend,
            "model_id": self.model_id,
            "peak_bytes": self.peak_bytes,
            "device_peak_bytes": self.device_peak_bytes,
            "weights_mapped": self.weights_mapped,
            "host_class": self.host_class,
            "measured_at": self.measured_at,
            "kaine_version": self.kaine_version,
            "source": self.source,
        }
        _str(raw, "component")
        _str(raw, "backend")
        _str(raw, "model_id")
        _int_nonneg(raw, "peak_bytes")
        _opt_int_nonneg(raw, "device_peak_bytes")
        _opt_bool(raw, "weights_mapped")
        _str(raw, "host_class")
        _str(raw, "measured_at")
        _str(raw, "kaine_version")
        _str_in(raw, "source", {"calibration", "observed"})

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Stable catalogue key."""
        return (self.component, self.backend, self.model_id, self.host_class)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FootprintEntry:
        """Construct from a dict, rejecting extra keys and wrong types."""
        extra = set(raw) - ALLOWED_KEYS
        if extra:
            raise ValueError(f"invalid footprint key: {sorted(extra)[0]!r}")

        return cls(
            component=_str(raw, "component"),
            backend=_str(raw, "backend"),
            model_id=_str(raw, "model_id"),
            peak_bytes=_int_nonneg(raw, "peak_bytes"),
            device_peak_bytes=_opt_int_nonneg(raw, "device_peak_bytes"),
            weights_mapped=_opt_bool(raw, "weights_mapped"),
            host_class=_str(raw, "host_class"),
            measured_at=_str(raw, "measured_at"),
            kaine_version=_str(raw, "kaine_version"),
            source=_str_in(raw, "source", {"calibration", "observed"}),
        )


ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "component",
        "backend",
        "model_id",
        "peak_bytes",
        "device_peak_bytes",
        "weights_mapped",
        "host_class",
        "measured_at",
        "kaine_version",
        "source",
    }
)


def _str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key!r} must be a string")
    return value


def _int_nonneg(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key!r} must be an integer")
    if value < 0:
        raise ValueError(f"{key!r} must be non-negative")
    return value


def _opt_int_nonneg(raw: dict[str, Any], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    return _int_nonneg(raw, key)


def _opt_bool(raw: dict[str, Any], key: str) -> bool | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{key!r} must be a boolean or None")
    return value


def _str_in(raw: dict[str, Any], key: str, allowed: set[str]) -> str:
    value = _str(raw, key)
    if value not in allowed:
        raise ValueError(f"{key!r} must be one of {allowed!r}")
    return value


@dataclass(frozen=True)
class FootprintCatalogue:
    """Immutable collection of footprint entries."""

    entries: tuple[FootprintEntry, ...]

    def get(
        self,
        component: str,
        backend: str,
        model_id: str,
        host_class: str,
    ) -> FootprintEntry | None:
        """Look up an entry by its catalogue key."""
        key = (component, backend, model_id, host_class)
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def merge(self, entry: FootprintEntry) -> FootprintCatalogue:
        """Return a new catalogue with ``entry`` inserted or merged by key."""
        new_entries = list(self.entries)

        for index, existing in enumerate(new_entries):
            if existing.key != entry.key:
                continue

            # Keep the entry with the larger peak; ties go to the newer timestamp.
            if entry.peak_bytes > existing.peak_bytes:
                chosen = entry
            elif entry.peak_bytes < existing.peak_bytes:
                chosen = existing
            elif _parse_dt(entry.measured_at) >= _parse_dt(existing.measured_at):
                chosen = entry
            else:
                chosen = existing

            # device_peak_bytes is the max of the two non-None values.
            devs = [
                value
                for value in (existing.device_peak_bytes, entry.device_peak_bytes)
                if value is not None
            ]
            device_peak = max(devs) if devs else None

            replacement = FootprintEntry(
                component=chosen.component,
                backend=chosen.backend,
                model_id=chosen.model_id,
                peak_bytes=chosen.peak_bytes,
                device_peak_bytes=device_peak,
                weights_mapped=chosen.weights_mapped,
                host_class=chosen.host_class,
                measured_at=chosen.measured_at,
                kaine_version=chosen.kaine_version,
                source=chosen.source,
            )
            new_entries[index] = replacement
            return FootprintCatalogue(tuple(new_entries))

        new_entries.append(entry)
        return FootprintCatalogue(tuple(new_entries))

    def to_dict(self) -> dict[str, Any]:
        """Serialize as ``{"version": 1, "entries": [...]}`` sorted by key."""
        sorted_entries = sorted(self.entries, key=lambda entry: entry.key)
        return {
            "version": 1,
            "entries": [asdict(entry) for entry in sorted_entries],
        }


class CatalogueError(ValueError):
    """Raised when a catalogue file cannot be loaded or contains invalid data."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"catalogue error at {path}: {reason}")


def _parse_dt(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_catalogue(path: Path) -> FootprintCatalogue:
    """Load a catalogue from ``path``; missing files yield an empty catalogue."""
    path = Path(path)
    if not path.exists():
        return FootprintCatalogue(())

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CatalogueError(path, f"invalid JSON: {exc}") from exc

    if raw.get("version") != 1:
        raise CatalogueError(path, f"unsupported version: {raw.get('version')!r}")

    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise CatalogueError(path, "'entries' is not a list")

    loaded: list[FootprintEntry] = []
    for index, item in enumerate(entries_raw):
        try:
            if not isinstance(item, dict):
                raise ValueError("entry is not an object")
            loaded.append(FootprintEntry.from_dict(item))
        except Exception as exc:  # noqa: BLE001
            raise CatalogueError(path, f"entry {index}: {exc}") from exc

    return FootprintCatalogue(tuple(loaded))


def save_catalogue(path: Path, catalogue: FootprintCatalogue) -> None:
    """Persist ``catalogue`` atomically as JSON."""
    write_json_atomic(Path(path), catalogue.to_dict())
