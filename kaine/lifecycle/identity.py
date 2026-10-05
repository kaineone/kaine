# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Entity identity for a being.

KAINE needs a stable notion of which being a piece of state belongs to. Each
being has one :class:`EntityIdentity`, persisted in its state tree at
``state/identity/entity.json``. The identity file is kept in plaintext because
key custody must read the ``entity_id`` *before* any key is unsealed, so it can
bind the right key to the encrypted container.

The ID format and the legacy derivation are intentionally frozen:

  - a minted ID is ``ent-`` plus 32 lowercase hex digits from a UUID4;
  - a legacy ID is ``legacy-`` plus the first 32 hex digits of
    ``sha256(source)`` where ``source`` is UTF-8;
  - legacy sources are ``bundle:<preservation_id>`` and ``tree:<digest>``.

Changing either the format or the derivation requires a migration change of its
own, because custody uses the ID in ciphertext bindings and key-file names.

``state/forks/`` and ``state/preservation/`` hold other beings as well as this
one, so they are never treated as evidence that *this* tree has already lived.
Only this tree's own lived artifacts (the developmental stage file, the Phantasia
world-model checkpoint, the Hypnos consolidation-divergence record and the
perception desired-state) count as evidence for deriving a legacy identity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from kaine.storage import resolve

log = logging.getLogger(__name__)

_ENTITY_ID_RE = re.compile(r"^(ent|legacy)-[0-9a-f]{32}$")
_ORIGINS = frozenset({"minted", "legacy"})

IDENTITY_PATH = Path("state/identity/entity.json")
SIDECAR_NAME = "identity.json"

OWN_LIVED_ARTIFACTS: tuple[Path, ...] = (
    Path("lifecycle/stage.json"),
    Path("phantasia/world_model.ckpt"),
    Path("hypnos/consolidation_divergence.json"),
    Path("perception/desired.json"),
)


class IdentityError(RuntimeError):
    """The identity file, sidecar or metadata is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class EntityIdentity:
    """The persistent identity of one being.

    ``entity_id`` is ``ent-<32 hex>`` for a minted root/fork identity, or
    ``legacy-<32 hex>`` for a deterministic legacy identity. ``lineage`` is the
    ordered list of ancestor entity IDs, oldest first. ``origin`` records how the
    ID was created. ``legacy_source`` is the source string for a legacy identity.
    """

    entity_id: str
    lineage: tuple[str, ...] = ()
    origin: str = "minted"
    minted_at: float = 0.0
    legacy_source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, str) or not _ENTITY_ID_RE.fullmatch(self.entity_id):
            raise IdentityError(f"invalid entity_id format: {self.entity_id!r}")
        if (
            not isinstance(self.lineage, tuple)
            or not all(isinstance(x, str) and _ENTITY_ID_RE.fullmatch(x) for x in self.lineage)
        ):
            raise IdentityError(f"invalid lineage: {self.lineage!r}")
        if self.origin not in _ORIGINS:
            raise IdentityError(f"invalid origin: {self.origin!r}")

        is_legacy_id = self.entity_id.startswith("legacy-")
        if self.origin == "legacy":
            if not is_legacy_id:
                raise IdentityError("origin 'legacy' requires a 'legacy-' entity_id")
            if not isinstance(self.legacy_source, str) or not self.legacy_source:
                raise IdentityError("legacy identity requires a non-empty legacy_source")
        else:
            if is_legacy_id:
                raise IdentityError("origin 'minted' requires an 'ent-' entity_id")
            if self.legacy_source is not None:
                raise IdentityError("minted identity must not have a legacy_source")

        if type(self.minted_at) not in (int, float) or not math.isfinite(self.minted_at):
            raise IdentityError(f"minted_at must be a finite number: {self.minted_at!r}")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "entity_id": self.entity_id,
            "lineage": list(self.lineage),
            "origin": self.origin,
            "minted_at": self.minted_at,
            "legacy_source": self.legacy_source,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EntityIdentity":
        """Reconstruct from a dict; raise :class:`IdentityError` on any problem."""
        if not isinstance(raw, Mapping):
            raise IdentityError("identity raw data must be a mapping")
        required = {"entity_id", "lineage", "origin", "minted_at", "legacy_source"}
        if set(raw.keys()) != required:
            raise IdentityError(
                f"identity dict has unexpected keys: {set(raw.keys()) ^ required}"
            )

        entity_id = raw["entity_id"]
        if not isinstance(entity_id, str):
            raise IdentityError("entity_id must be a string")

        lineage_raw = raw["lineage"]
        if not isinstance(lineage_raw, (list, tuple)):
            raise IdentityError("lineage must be a list or tuple")
        if not all(isinstance(x, str) for x in lineage_raw):
            raise IdentityError("lineage entries must be strings")
        lineage = tuple(lineage_raw)

        origin = raw["origin"]
        if not isinstance(origin, str):
            raise IdentityError("origin must be a string")

        minted_at = raw["minted_at"]
        if type(minted_at) not in (int, float) or not math.isfinite(float(minted_at)):
            raise IdentityError("minted_at must be a finite number")
        minted_at = float(minted_at)

        legacy_source = raw["legacy_source"]
        if legacy_source is not None and not isinstance(legacy_source, str):
            raise IdentityError("legacy_source must be a string or None")

        try:
            return cls(
                entity_id=entity_id,
                lineage=lineage,
                origin=origin,
                minted_at=minted_at,
                legacy_source=legacy_source,
            )
        except IdentityError:
            raise
        except Exception as exc:
            raise IdentityError(f"invalid identity: {exc}") from exc


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        # Permission tightening is best effort. Some filesystems (e.g. FAT or
        # certain network mounts) reject chmod, and the file was already
        # created owner-only, so a failure here is acceptable.
        pass


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` created owner-only from the start."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    _chmod_quietly(path, 0o600)


def _file_sha256(path: Path) -> str:
    """SHA-256 hex digest of a file, streamed in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_identity(path: Path | None = None) -> EntityIdentity | None:
    """Load the identity at ``path`` (default ``IDENTITY_PATH`` resolved).

    Returns ``None`` when the file does not exist. Raises :class:`IdentityError`
    when it exists but cannot be read or parsed.
    """
    target = resolve(path) if path is not None else resolve(IDENTITY_PATH)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot read identity file {target}: {exc}") from exc
    return EntityIdentity.from_dict(raw)


def save_identity(identity: EntityIdentity, path: Path | None = None) -> None:
    """Persist ``identity`` atomically, owner-only, refusing to clobber another being.

    If ``path`` already holds an identity with a different ``entity_id``,
    :class:`IdentityError` is raised and the file is left unchanged.
    """
    target = resolve(path) if path is not None else resolve(IDENTITY_PATH)
    if target.exists():
        try:
            existing = EntityIdentity.from_dict(json.loads(target.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityError(f"cannot read existing identity file {target}: {exc}") from exc
        if existing.entity_id != identity.entity_id:
            raise IdentityError(
                f"refusing to overwrite identity file {target}: "
                f"existing {existing.entity_id!r} != new {identity.entity_id!r}"
            )

    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_quietly(target.parent, 0o700)
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(identity.to_dict(), indent=2, sort_keys=True)
    _write_private(tmp, payload)
    os.replace(tmp, target)


def mint_identity(*, now: Callable[[], float] = time.time) -> EntityIdentity:
    """Create a new root being identity."""
    return EntityIdentity(
        entity_id="ent-" + uuid.uuid4().hex,
        lineage=(),
        origin="minted",
        minted_at=now(),
        legacy_source=None,
    )


def fork_identity(parent: EntityIdentity, *, now: Callable[[], float] = time.time) -> EntityIdentity:
    """Create a fork identity: new minted ID, lineage extended by the parent."""
    return EntityIdentity(
        entity_id="ent-" + uuid.uuid4().hex,
        lineage=parent.lineage + (parent.entity_id,),
        origin="minted",
        minted_at=now(),
        legacy_source=None,
    )


def legacy_identity(source: str, *, now: Callable[[], float] = time.time) -> EntityIdentity:
    """Create a deterministic legacy identity from ``source``."""
    if not isinstance(source, str) or not source:
        raise IdentityError("legacy source must be a non-empty string")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    return EntityIdentity(
        entity_id="legacy-" + digest,
        lineage=(),
        origin="legacy",
        minted_at=now(),
        legacy_source=source,
    )


def identity_of_snapshot(snap: object) -> EntityIdentity | None:
    """Read the identity from a snapshot's ``metadata`` dict.

    Returns ``None`` when absent. Raises :class:`IdentityError` when malformed.
    """
    raw = snap.metadata.get("identity")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise IdentityError("snapshot identity metadata must be a mapping")
    return EntityIdentity.from_dict(raw)


def write_identity_sidecar(container_dir: Path, identity: EntityIdentity) -> None:
    """Write a plaintext sidecar with only ``entity_id`` and ``lineage``."""
    target = Path(container_dir) / SIDECAR_NAME
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_quietly(target.parent, 0o700)
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(
        {"entity_id": identity.entity_id, "lineage": list(identity.lineage)},
        indent=2,
        sort_keys=True,
    )
    _write_private(tmp, payload)
    os.replace(tmp, target)


def read_identity_sidecar(container_dir: Path) -> tuple[str, tuple[str, ...]] | None:
    """Read a plaintext sidecar. Return ``None`` when absent.

    Raises :class:`IdentityError` when the sidecar exists but is unreadable or
    contains malformed identity data.
    """
    target = Path(container_dir) / SIDECAR_NAME
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityError(f"cannot read identity sidecar {target}: {exc}") from exc
    if not isinstance(raw, dict) or set(raw.keys()) != {"entity_id", "lineage"}:
        raise IdentityError("identity sidecar must contain exactly entity_id and lineage")
    entity_id = raw["entity_id"]
    lineage_raw = raw["lineage"]
    if not isinstance(entity_id, str) or not _ENTITY_ID_RE.fullmatch(entity_id):
        raise IdentityError("identity sidecar has malformed entity_id")
    if (
        not isinstance(lineage_raw, (list, tuple))
        or not all(isinstance(x, str) and _ENTITY_ID_RE.fullmatch(x) for x in lineage_raw)
    ):
        raise IdentityError("identity sidecar has malformed lineage")
    return entity_id, tuple(lineage_raw)


def check_sidecar_agrees(
    sidecar: tuple[str, tuple[str, ...]] | None,
    identity: EntityIdentity | None,
) -> None:
    """Verify a plaintext sidecar matches the in-container identity.

    Missing sidecar or missing identity is acceptable; a mismatch raises
    :class:`IdentityError`.
    """
    if sidecar is None or identity is None:
        return
    sidecar_id, sidecar_lineage = sidecar
    if sidecar_id != identity.entity_id or sidecar_lineage != identity.lineage:
        raise IdentityError(
            f"identity sidecar disagrees: sidecar {sidecar_id!r} lineage "
            f"{sidecar_lineage!r} vs identity {identity.entity_id!r} lineage "
            f"{identity.lineage!r}"
        )


def own_lived_artifacts(state_root: Path | str = "state") -> list[Path]:
    """Return this tree's own lived artifacts that currently exist.

    Only the indicators in :data:`OWN_LIVED_ARTIFACTS` are considered; forks/
    and preservation/ are excluded. Each artifact may be a file or a directory.
    """
    root = resolve(state_root)
    out: list[Path] = []
    for rel in OWN_LIVED_ARTIFACTS:
        candidate = root / rel
        try:
            if candidate.exists():
                out.append(candidate)
        except OSError:
            continue
    return out


def tree_digest(state_root: Path | str, artifacts: list[Path]) -> str:
    """Compute the deterministic digest of ``artifacts`` relative to ``state_root``.

    The digest is the SHA-256 hex of newline-joined, sorted lines of the form
    ``f"{relpath}\0{filesha}"``. For a directory artifact, one line is emitted
    for each regular file inside it recursively. Files are streamed in 1 MiB
    chunks.
    """
    root = resolve(state_root)
    lines: list[str] = []
    # A top-level artifact that is a symlink is followed: operators relocate a
    # being's data (for example to bulk storage) by linking it, and the data is
    # still this being's own. Symlinks inside a directory artifact are skipped so
    # the walk cannot loop or leave the artifact.
    for artifact in artifacts:
        try:
            if artifact.is_dir():
                for dirpath, _dirnames, filenames in os.walk(artifact, followlinks=False):
                    rel_dir = Path(dirpath).relative_to(root)
                    for filename in filenames:
                        file_path = Path(dirpath) / filename
                        if file_path.is_symlink():
                            continue
                        relpath = (rel_dir / filename).as_posix()
                        lines.append(f"{relpath}\0{_file_sha256(file_path)}")
            elif artifact.is_file():
                relpath = artifact.relative_to(root).as_posix()
                lines.append(f"{relpath}\0{_file_sha256(artifact)}")
        except (OSError, ValueError) as exc:
            # A legacy ID is derived once and frozen; an artifact that cannot be
            # read must stop the derivation rather than silently change it.
            raise IdentityError(f"cannot digest lived artifact {artifact}: {exc}") from exc
    lines.sort()
    joined = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


def resolve_spawn_identity(
    state_root: Path | str = "state", *, now: Callable[[], float] = time.time
) -> EntityIdentity:
    """Resolve (and persist) this tree's identity at spawn/restart time.

    - If ``<state_root>/identity/entity.json`` exists, return it unchanged.
    - If it is absent and no own lived artifacts exist, mint a new identity.
    - If it is absent and own lived artifacts exist, derive a deterministic
      legacy identity from ``tree:<digest>`` and persist it.

    ``forks/`` and ``preservation/`` are never considered lived evidence.
    """
    root = resolve(state_root)
    identity_path = root / "identity" / "entity.json"
    existing = load_identity(identity_path)
    if existing is not None:
        return existing

    artifacts = own_lived_artifacts(root)
    if not artifacts:
        identity = mint_identity(now=now)
    else:
        digest = tree_digest(root, artifacts)
        identity = legacy_identity("tree:" + digest, now=now)

    save_identity(identity, identity_path)
    return identity


def has_prior_lived_history_in_lineage(
    identity: EntityIdentity | None,
    state_root: Path | str = "state",
    bundle_roots: Iterable[Path | str] = (),
) -> bool:
    """Return whether this tree holds prior lived history for ``identity``'s lineage.

    ``None`` counts as lived (unknown lineage). Otherwise, the query reads only
    plaintext metadata: fork sidecars, preservation manifests, and any
    configured bundle-root manifests. Records without an identity, or
    unreadable/broken foreign records, are skipped with a warning. This function
    never raises because of a foreign or broken record.
    """
    if identity is None:
        return True

    root = resolve(state_root)
    target_ids = {identity.entity_id} | set(identity.lineage)

    forks_root = root / "forks"
    try:
        if forks_root.is_dir():
            for entry in forks_root.iterdir():
                try:
                    sidecar = read_identity_sidecar(entry)
                except IdentityError as exc:
                    log.warning(
                        "Skipping unreadable fork identity sidecar %s: %s",
                        entry / SIDECAR_NAME,
                        exc,
                    )
                    continue
                except OSError as exc:
                    log.warning(
                        "Skipping unreadable fork identity sidecar %s: %s",
                        entry / SIDECAR_NAME,
                        exc,
                    )
                    continue
                if sidecar is None:
                    continue
                # Its own or an ancestor's record, or a descendant's: a fork
                # whose lineage names this being proves this being lived.
                if sidecar[0] in target_ids or identity.entity_id in sidecar[1]:
                    return True
    except OSError as exc:
        log.warning("Cannot enumerate fork snapshots under %s: %s", forks_root, exc)

    # Preservation bundles: the legacy in-tree location plus every configured
    # bundle root (preservation out_roots default to ``backups/``).
    for bundle_root in [root / "preservation", *(resolve(r) for r in bundle_roots)]:
        try:
            if not bundle_root.is_dir():
                continue
            entries = list(bundle_root.iterdir())
        except OSError as exc:
            log.warning("Cannot enumerate preservation bundles under %s: %s", bundle_root, exc)
            continue
        for entry in entries:
            manifest_path = entry / "manifest.json"
            try:
                if not manifest_path.is_file():
                    continue
                raw = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Skipping unreadable preservation manifest %s: %s", manifest_path, exc)
                continue
            if not isinstance(raw, dict):
                continue
            identity_obj = raw.get("identity")
            if not isinstance(identity_obj, dict):
                continue
            record_id = identity_obj.get("entity_id")
            if isinstance(record_id, str) and record_id in target_ids:
                return True
            record_lineage = identity_obj.get("lineage")
            if isinstance(record_lineage, list) and identity.entity_id in record_lineage:
                return True

    return False


def lived_before(
    identity: EntityIdentity | None,
    state_root: Path | str = "state",
    bundle_roots: Iterable[Path | str] = (),
) -> bool:
    """Return whether this being has lived before this boot.

    Implements the maturation-gate liveness rule approved for KAINE: a being is
    treated as already-lived (and therefore must never be regressed into a womb)
    when any of the following hold:

      * its identity is unknown (``None``);
      * this state tree contains any of its own lived artifacts
        (:data:`OWN_LIVED_ARTIFACTS`), which deliberately excludes ``forks/``
        and ``preservation/``;
      * ``forks/``, in-tree ``preservation/`` or any configured bundle root
        contains a record whose sidecar or manifest names this being or one of
        its ancestors.

    Foreign snapshots or bundles are not counted as this being's own history.
    """
    if identity is None:
        return True
    if own_lived_artifacts(state_root):
        return True
    return has_prior_lived_history_in_lineage(identity, state_root, bundle_roots)
