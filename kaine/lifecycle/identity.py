# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Entity identity for an entity.

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

``state/forks/`` and ``state/preservation/`` hold other entities as well as this
one, so they are never treated as evidence that *this* tree has already lived.
Only this tree's own lived artifacts (the developmental stage file, the world-model checkpoint,
the sleep module's consolidation-divergence record and the
perception desired-state) count as evidence for deriving a legacy identity.
Each is recognized under its old and its new name, and the legacy digest uses the
old name for both, so renaming a tree's directories does not change its legacy
identity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from kaine import legacy_names
from kaine.legacy_aliases import lived_artifact_paths
from kaine.storage import resolve

log = logging.getLogger(__name__)

_ENTITY_ID_RE = re.compile(r"^(ent|legacy)-[0-9a-f]{32}$")
_ORIGINS = frozenset({"minted", "legacy"})

IDENTITY_PATH = Path("state/identity/entity.json")
SIDECAR_NAME = "identity.json"

OWN_LIVED_ARTIFACTS: tuple[Path, ...] = (Path("lifecycle/stage.json"),) + tuple(
    Path(rel) for rel in lived_artifact_paths()
)


class IdentityError(RuntimeError):
    """The identity file, sidecar or metadata is missing, malformed or inconsistent."""


def _valid_name(name: object) -> bool:
    """The shared name check (see ``is_valid_name`` in the self-model document)."""
    from kaine.modules.self_model.document import is_valid_name

    return is_valid_name(name)


@dataclass(frozen=True)
class EntityIdentity:
    """The persistent identity of one being.

    ``entity_id`` is ``ent-<32 hex>`` for a minted root/fork identity, or
    ``legacy-<32 hex>`` for a deterministic legacy identity. ``lineage`` is the
    ordered list of ancestor entity IDs, oldest first. ``origin`` records how the
    ID was created. ``legacy_source`` is the source string for a legacy identity.
    ``name`` is the entity's launch name ("Kaine <Surname>"); it is ``None`` until
    boot assigns one and is written to disk only when set.
    """

    entity_id: str
    lineage: tuple[str, ...] = ()
    origin: str = "minted"
    minted_at: float = 0.0
    legacy_source: str | None = None
    name: str | None = None

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

        if self.name is not None and not _valid_name(self.name):
            raise IdentityError(f"name must be a non-empty single-line string: {self.name!r}")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict representation.

        ``name`` is included only when set, so an unnamed identity serializes
        exactly as it did before names existed.
        """
        out: dict[str, Any] = {
            "entity_id": self.entity_id,
            "lineage": list(self.lineage),
            "origin": self.origin,
            "minted_at": self.minted_at,
            "legacy_source": self.legacy_source,
        }
        if self.name is not None:
            out["name"] = self.name
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EntityIdentity":
        """Reconstruct from a dict; raise :class:`IdentityError` on any problem."""
        if not isinstance(raw, Mapping):
            raise IdentityError("identity raw data must be a mapping")
        required = {"entity_id", "lineage", "origin", "minted_at", "legacy_source"}
        keys = set(raw.keys())
        if keys != required and keys != required | {"name"}:
            raise IdentityError(
                f"identity dict has unexpected keys: {keys ^ required}"
            )
        name = raw.get("name")
        if "name" in raw and not isinstance(name, str):
            raise IdentityError("name must be a string when present")

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
                name=name,
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


def save_identity(
    identity: EntityIdentity, path: Path | None = None, *, replace_name: bool = False
) -> None:
    """Persist ``identity`` atomically, owner-only, refusing to clobber another being.

    If ``path`` already holds an identity with a different ``entity_id``,
    :class:`IdentityError` is raised and the file is left unchanged. A stored
    ``name`` is never replaced by a different one (same refusal); adding a name
    to a stored identity that has none is allowed. ``replace_name=True`` (only
    for a revive, where the revived entity's own name wins) allows the stored
    name of the same ``entity_id`` to change and logs a warning naming both.
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
        if replace_name and existing.name is not None and existing.name != identity.name:
            log.warning(
                "replacing the stored name %r of identity %s with %r",
                existing.name,
                identity.entity_id,
                identity.name,
            )
        elif existing.name is not None and existing.name != identity.name:
            raise IdentityError(
                f"refusing to replace the name of identity file {target}: "
                f"existing {existing.name!r} != new {identity.name!r}"
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


def fork_identity(
    parent: EntityIdentity,
    *,
    now: Callable[[], float] = time.time,
    rng: random.Random | None = None,
) -> EntityIdentity:
    """Create a fork identity: new minted ID, lineage extended by the parent.

    The fork is a new entity and gets its own newly drawn name, never the
    parent's. The parent's name is not copied.
    """
    from kaine.modules.self_model.document import generate_launch_name

    return EntityIdentity(
        entity_id="ent-" + uuid.uuid4().hex,
        lineage=parent.lineage + (parent.entity_id,),
        origin="minted",
        minted_at=now(),
        legacy_source=None,
        name=generate_launch_name(rng=rng, exclude=parent.name),
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
    An artifact whose existence cannot be checked counts as present.
    """
    root = resolve(state_root)
    out: list[Path] = []
    for rel in OWN_LIVED_ARTIFACTS:
        candidate = root / rel
        try:
            exists = candidate.exists()
        except OSError:
            exists = True
        if exists:
            out.append(candidate)
    return out


def _canonical_relpath(relpath: str) -> str:
    """Return the legacy (old) name for a lived-artifact relative path.

    This keeps the legacy digest stable when a tree's directories are renamed.
    """
    for entry in legacy_names.LIVED_ARTIFACTS:
        new = entry["new"]
        if relpath == new or relpath.startswith(new + "/"):
            return entry["old"] + relpath[len(new):]
    return relpath


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
    # an entity's data (for example to bulk storage) by linking it, and the data is
    # still this entity's own. Symlinks inside a directory artifact are skipped so
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
                        relpath = _canonical_relpath((rel_dir / filename).as_posix())
                        lines.append(f"{relpath}\0{_file_sha256(file_path)}")
            elif artifact.is_file():
                relpath = _canonical_relpath(artifact.relative_to(root).as_posix())
                lines.append(f"{relpath}\0{_file_sha256(artifact)}")
        except (OSError, ValueError) as exc:
            # A legacy ID is derived once and frozen; an artifact that cannot be
            # read must stop the derivation rather than silently change it.
            raise IdentityError(f"cannot digest lived artifact {artifact}: {exc}") from exc
    lines.sort()
    joined = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


class _DocumentUnreadable(Exception):
    """The self-model document exists but could not be read."""


def _self_model_document_name(document_path: Path | None) -> str | None:
    """The name in the self-model document at ``document_path``, or ``None``.

    ``None`` when the path is absent, the document does not exist, or it has no
    (valid) name. Raises :class:`_DocumentUnreadable` when the document exists but
    cannot be read (corrupt, wrong key, permissions), so the caller can defer.
    """
    if document_path is None:
        return None
    try:
        if not document_path.exists():
            return None
        from kaine.modules.self_model.document import load as load_document

        name = load_document(document_path).name
    except Exception as exc:
        raise _DocumentUnreadable(str(exc)) from exc
    return name if _valid_name(name) else None


def name_identity(
    identity: EntityIdentity, *, self_model_path: Path | None = None
) -> EntityIdentity:
    """Return ``identity`` with a name; an existing name is never replaced.

    An unnamed identity adopts the self-model document's name when the document
    at ``self_model_path`` has one, otherwise it draws "Kaine <Surname>". When the
    document exists but cannot be read, naming is deferred: a warning is logged
    and the identity is returned unnamed, so the next boot tries again. The
    result is not persisted.
    """
    if identity.name is not None:
        return identity
    from kaine.modules.self_model.document import generate_launch_name

    try:
        name = _self_model_document_name(self_model_path)
    except _DocumentUnreadable as exc:
        log.warning(
            "cannot read the self-model document %s; not naming the entity this boot: %s",
            self_model_path,
            exc,
        )
        return identity
    return replace(identity, name=name or generate_launch_name())


def _save_naming(identity: EntityIdentity, path: Path) -> EntityIdentity:
    """Save a freshly named identity. When a concurrent boot named the file first,
    return the stored named identity (same ``entity_id``) instead of failing."""
    try:
        save_identity(identity, path)
    except IdentityError:
        stored = load_identity(path)
        if stored is not None and stored.entity_id == identity.entity_id and stored.name:
            log.info("identity %s was named by another boot; keeping %r", stored.entity_id, stored.name)
            return stored
        raise
    return identity


def resolve_spawn_identity(
    state_root: Path | str = "state",
    *,
    now: Callable[[], float] = time.time,
    self_model_path: Path | None = None,
) -> EntityIdentity:
    """Resolve (and persist) this tree's identity at spawn/restart time.

    - If ``<state_root>/identity/entity.json`` exists, return it (an identity
      without a name is named and saved, see :func:`name_identity`).
    - If it is absent and no own lived artifacts exist, mint a new identity.
    - If it is absent and own lived artifacts exist, derive a deterministic
      legacy identity from ``tree:<digest>`` and persist it.

    Every identity returned has a name unless the self-model document exists but
    cannot be read, in which case naming is deferred to the next boot.
    ``self_model_path`` is the self-model
    document consulted for an existing name; it defaults to
    ``<state_root>/self_model/self_model.json``.

    ``forks/`` and ``preservation/`` are never considered lived evidence.
    """
    root = resolve(state_root)
    identity_path = root / "identity" / "entity.json"
    if self_model_path is None:
        self_model_path = root / "self_model" / "self_model.json"
    existing = load_identity(identity_path)
    if existing is not None:
        if existing.name is not None:
            return existing
        named = name_identity(existing, self_model_path=self_model_path)
        if named.name is None:
            return existing
        return _save_naming(named, identity_path)

    artifacts = own_lived_artifacts(root)
    if not artifacts:
        identity = mint_identity(now=now)
    else:
        digest = tree_digest(root, artifacts)
        identity = legacy_identity("tree:" + digest, now=now)

    identity = name_identity(identity, self_model_path=self_model_path)
    if identity.name is None:
        save_identity(identity, identity_path)
        return identity
    identity = _save_naming(identity, identity_path)
    return identity


def has_prior_lived_history_in_lineage(
    identity: EntityIdentity | None,
    state_root: Path | str = "state",
    bundle_roots: Iterable[Path | str] = (),
) -> bool:
    """Return whether this tree holds prior lived history for ``identity``'s lineage.

    ``None`` counts as lived (unknown lineage). Otherwise, the query reads only
    plaintext metadata: fork sidecars, preservation manifests, and any
    configured bundle-root manifests. Unreadable, malformed, or unidentified
    records are treated as evidence of a lived being and return ``True``,
    because ambiguity must resolve to "lived". This function still never raises.
    """
    if identity is None:
        return True

    root = resolve(state_root)
    target_ids = {identity.entity_id} | set(identity.lineage)

    forks_root = root / "forks"
    try:
        forks_present = forks_root.is_dir()
    except OSError as exc:
        log.warning("Cannot inspect %s; treating as prior lived history: %s", forks_root, exc)
        return True
    if forks_present:
        try:
            entries = list(forks_root.iterdir())
        except OSError as exc:
            log.warning(
                "Cannot enumerate fork snapshots under %s; treating as prior lived history: %s",
                forks_root,
                exc,
            )
            return True
        for entry in entries:
            sidecar_path = entry / SIDECAR_NAME
            try:
                sidecar = read_identity_sidecar(entry)
            except IdentityError as exc:
                log.warning(
                    "Treating unreadable fork identity sidecar %s as prior lived history: %s",
                    sidecar_path,
                    exc,
                )
                return True
            except OSError as exc:
                log.warning(
                    "Treating unreadable fork identity sidecar %s as prior lived history: %s",
                    sidecar_path,
                    exc,
                )
                return True
            if sidecar is None:
                # A snapshot with no identity sidecar is unidentified: lived.
                log.warning(
                    "Treating fork snapshot %s without an identity sidecar as prior lived history",
                    entry,
                )
                return True
            # Its own or an ancestor's record, or a descendant's: a fork
            # whose lineage names this entity proves this entity lived.
            if sidecar[0] in target_ids or identity.entity_id in sidecar[1]:
                return True

    # Preservation bundles: the legacy in-tree location plus every configured
    # bundle root (preservation out_roots default to ``backups/``).
    for bundle_root in [root / "preservation", *(resolve(r) for r in bundle_roots)]:
        try:
            if not bundle_root.is_dir():
                continue
            entries = list(bundle_root.iterdir())
        except OSError as exc:
            log.warning(
                "Cannot enumerate preservation bundles under %s; treating as prior lived history: %s",
                bundle_root,
                exc,
            )
            return True
        for entry in entries:
            manifest_path = entry / "manifest.json"
            try:
                if not manifest_path.is_file():
                    continue
                raw_text = manifest_path.read_text()
            except OSError as exc:
                log.warning(
                    "Treating unreadable preservation manifest %s as prior lived history: %s",
                    manifest_path,
                    exc,
                )
                return True
            try:
                raw = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Treating malformed preservation manifest %s as prior lived history: %s",
                    manifest_path,
                    exc,
                )
                return True
            if not isinstance(raw, dict):
                log.warning(
                    "Treating preservation manifest with non-object JSON as prior lived history: %s",
                    manifest_path,
                )
                return True
            identity_obj = raw.get("identity")
            if not isinstance(identity_obj, dict):
                log.warning(
                    "Treating preservation manifest without an identity object as prior lived history: %s",
                    manifest_path,
                )
                return True
            record_id = identity_obj.get("entity_id")
            if not isinstance(record_id, str) or not record_id:
                log.warning(
                    "Treating preservation manifest with a malformed identity as prior lived history: %s",
                    manifest_path,
                )
                return True
            if record_id in target_ids:
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
    """Return whether this entity has lived before this boot.

    Implements the maturation-gate liveness rule approved for KAINE: an entity is
    treated as already-lived (and therefore must never be regressed into a stimulus source)
    when any of the following hold:

      * its identity is unknown (``None``);
      * this state tree contains any of its own lived artifacts
        (:data:`OWN_LIVED_ARTIFACTS`), which deliberately excludes ``forks/``
        and ``preservation/``;
      * ``forks/``, in-tree ``preservation/`` or any configured bundle root
        contains a readable record whose sidecar or manifest names this entity
        or one of its ancestors, or a descendant whose lineage names this entity;
      * a fork sidecar, preservation manifest, or bundle manifest is unreadable,
        malformed, or lacks an identity object — every ambiguity resolves to
        "lived".

    Foreign snapshots or bundles are not counted as this entity's own history.
    """
    if identity is None:
        return True
    if own_lived_artifacts(state_root):
        return True
    return has_prior_lived_history_in_lineage(identity, state_root, bundle_roots)
