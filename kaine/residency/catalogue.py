# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Content-free footprint catalogue: measured peak memory per component."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine import __version__ as kaine_version_str
from kaine.state_io import write_json_atomic
from kaine.storage import resolve

logger = logging.getLogger(__name__)

DEFAULT_CATALOGUE_PATH = "state/residency/footprints.json"

_HOST_CLASS: set[str] = {"unified", "discrete", "cpu"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Entry:
    component: str
    backend: str
    model_id: str
    bytes: int
    device: str | None = None
    device_bytes: int | None = None
    mapped: bool = False
    quantization: str | None = None
    weights_sha256: str | None = None
    host_class: str = "cpu"
    measured_at: str = field(default_factory=_now_iso)
    kaine_version: str = kaine_version_str

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "backend": self.backend,
            "model_id": self.model_id,
            "bytes": self.bytes,
            "device": self.device,
            "device_bytes": self.device_bytes,
            "mapped": self.mapped,
            "quantization": self.quantization,
            "weights_sha256": self.weights_sha256,
            "host_class": self.host_class,
            "measured_at": self.measured_at,
            "kaine_version": self.kaine_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entry":
        expected = {f.name for f in fields(cls)}
        unknown = set(d.keys()) - expected
        if unknown:
            raise ValueError(f"unknown keys: {sorted(unknown)}")

        for f in fields(cls):
            if f.name not in d:
                raise ValueError(f"missing field: {f.name}")

        component = d["component"]
        backend = d["backend"]
        model_id = d["model_id"]
        bytes_ = d["bytes"]
        device = d["device"]
        device_bytes = d["device_bytes"]
        mapped = d["mapped"]
        quantization = d["quantization"]
        weights_sha256 = d["weights_sha256"]
        host_class = d["host_class"]
        measured_at = d["measured_at"]
        kaine_version = d["kaine_version"]

        if not isinstance(component, str):
            raise ValueError("component must be str")
        if not isinstance(backend, str):
            raise ValueError("backend must be str")
        if not isinstance(model_id, str):
            raise ValueError("model_id must be str")
        if not isinstance(bytes_, int) or isinstance(bytes_, bool):
            raise ValueError("bytes must be int")
        if bytes_ < 0:
            raise ValueError("bytes must be non-negative")
        if device is not None and not isinstance(device, str):
            raise ValueError("device must be str or None")
        if device_bytes is not None:
            if not isinstance(device_bytes, int) or isinstance(device_bytes, bool):
                raise ValueError("device_bytes must be int or None")
            if device_bytes < 0:
                raise ValueError("device_bytes must be non-negative")
        if not isinstance(mapped, bool):
            raise ValueError("mapped must be bool")
        if quantization is not None and not isinstance(quantization, str):
            raise ValueError("quantization must be str or None")
        if weights_sha256 is not None and not isinstance(weights_sha256, str):
            raise ValueError("weights_sha256 must be str or None")
        if not isinstance(host_class, str):
            raise ValueError("host_class must be str")
        if host_class not in _HOST_CLASS:
            raise ValueError(f"host_class must be one of {_HOST_CLASS}")
        if not isinstance(measured_at, str):
            raise ValueError("measured_at must be str")
        if not isinstance(kaine_version, str):
            raise ValueError("kaine_version must be str")

        return cls(
            component=component,
            backend=backend,
            model_id=model_id,
            bytes=bytes_,
            device=device,
            device_bytes=device_bytes,
            mapped=mapped,
            quantization=quantization,
            weights_sha256=weights_sha256,
            host_class=host_class,
            measured_at=measured_at,
            kaine_version=kaine_version,
        )


def _resolve_path(path: str | Path | None) -> Path:
    return Path(resolve(DEFAULT_CATALOGUE_PATH if path is None else path))


def load_catalogue(path: str | Path | None = None) -> tuple[Entry, ...]:
    """Load catalogue entries; never raises. Invalid entries are skipped."""
    target = _resolve_path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("could not read catalogue %s: %s", target, exc)
        return ()

    if not isinstance(data, list):
        logger.debug("catalogue %s is not a list", target)
        return ()

    entries: list[Entry] = []
    skipped = 0
    for raw in data:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        try:
            entries.append(Entry.from_dict(raw))
        except Exception as exc:
            skipped += 1
            logger.debug("skipping catalogue entry: %s", exc)

    if skipped:
        logger.warning("skipped %d invalid catalogue entries in %s", skipped, target)

    return tuple(entries)


def write_catalogue(
    entries: tuple[Entry, ...] | list[Entry],
    path: str | Path | None = None,
) -> Path:
    """Write catalogue atomically after round-trip validation."""
    target = _resolve_path(path)

    payload: list[dict[str, Any]] = []
    for entry in entries:
        round_tripped = Entry.from_dict(entry.to_dict())
        payload.append(round_tripped.to_dict())

    write_json_atomic(target, payload)
    return target


def upsert(
    entries: tuple[Entry, ...] | list[Entry],
    new: Entry,
) -> tuple[Entry, ...]:
    """Replace an entry with matching identity or append; order is stable."""
    identity = (new.component, new.backend, new.model_id, new.host_class)
    result: list[Entry] = []
    replaced = False
    for entry in entries:
        if (
            entry.component,
            entry.backend,
            entry.model_id,
            entry.host_class,
        ) == identity:
            result.append(new)
            replaced = True
        else:
            result.append(entry)
    if not replaced:
        result.append(new)
    return tuple(result)


def footprint_bytes(
    entries: tuple[Entry, ...] | list[Entry],
    component: str,
    *,
    backend: str | None = None,
    model_id: str | None = None,
    host_class: str | None = None,
) -> int | None:
    """Largest calibrated system-memory footprint matching the filters."""
    best: int | None = None
    for entry in entries:
        if entry.component != component:
            continue
        if backend is not None and entry.backend != backend:
            continue
        if model_id is not None and entry.model_id != model_id:
            continue
        if host_class is not None and entry.host_class != host_class:
            continue
        if best is None or entry.bytes > best:
            best = entry.bytes
    return best

