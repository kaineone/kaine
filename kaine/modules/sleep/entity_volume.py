# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-entity subdirectories in volumes that several entities may share.

In the compose deployment the main cycle and the study runner mount the same
organ-adapters and trainer-jobs volumes. Each entity writes only under
``<volume>/<entity_id>/``, so the layout itself says whose a file is. The id
is checked against the identity format before it is ever used as a directory
name, so it can never carry a path separator or ``..``.
"""
from __future__ import annotations

import os
from pathlib import Path


class EntityVolumeError(ValueError):
    """An entity id or an entity subdirectory failed a containment check."""


def is_entity_id(value: object) -> bool:
    """True when ``value`` is in the identity format (``kaine.lifecycle.identity``)."""
    from kaine.lifecycle.identity import is_entity_id as _is_entity_id

    return _is_entity_id(value)


def require_entity_id(entity_id: object) -> str:
    """Return ``entity_id`` when it is in the identity format, else raise."""
    if not is_entity_id(entity_id):
        raise EntityVolumeError(
            f"refusing to use {entity_id!r} as an entity directory: it is not an "
            "entity id (ent-<32 hex> or legacy-<32 hex>)"
        )
    return str(entity_id)


def entity_subdir(volume: Path, entity_id: object, *, create: bool = False) -> Path:
    """Return ``<volume>/<entity_id>``, checked to be that entity's own directory.

    Refuses an id outside the identity format, an existing subdirectory that is
    a symlink or not a directory, and a subdirectory whose real path is not a
    direct child of the volume's real path. With ``create`` the volume and the
    subdirectory are created (owner-only) when missing.
    """
    eid = require_entity_id(entity_id)
    volume = Path(volume)
    sub = volume / eid
    if create:
        volume.mkdir(parents=True, exist_ok=True)
        if not sub.is_symlink():
            try:
                sub.mkdir(mode=0o700)
            except FileExistsError:
                pass
    if sub.is_symlink():
        raise EntityVolumeError(f"refusing entity directory {sub}: it is a symlink")
    if sub.exists() and not sub.is_dir():
        raise EntityVolumeError(f"refusing entity directory {sub}: it is not a directory")
    if sub.exists():
        real = Path(os.path.realpath(sub))
        if real.parent != Path(os.path.realpath(volume)) or real.name != eid:
            raise EntityVolumeError(
                f"refusing entity directory {sub}: its real path {real} is not "
                f"directly under the volume"
            )
    return sub


def current_entity_id() -> str | None:
    """The entity id in ``state/identity/entity.json``, or ``None`` when unreadable."""
    from kaine.lifecycle.identity import IdentityError, load_identity

    try:
        identity = load_identity()
    except IdentityError:
        return None
    return identity.entity_id if identity is not None else None
