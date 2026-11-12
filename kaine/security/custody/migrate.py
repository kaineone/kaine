# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""One-way migration from the per-operator key (v1/plaintext) to per-entity encryption (v2).

``python -m kaine.security.custody migrate`` walks the state root, backs up each
entity directory, decrypts v1 envelopes with the operator key (or reads
plaintext), re-encrypts under a fresh per-entity DEK with v2 envelopes, verifies
every file by decrypting and comparing hashes, and only then replaces the
original.  Content-free logging only: never logs plaintext, DEKs or key material.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from kaine.security.crypto import CryptoConfig, StateEncryptor, is_encrypted
from kaine.security.custody.envelope import VALID_KINDS, is_v2
from kaine.security.custody.keyring import KekProvider, KeyRing

log = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """Raised when the migration cannot proceed or fails unrecoverably."""


@dataclass
class FileMigrationResult:
    """Result of migrating a single file (content-free: no plaintext or keys)."""

    path: str
    action: str  # "encrypted", "re-encrypted", "skipped-v2", "error"
    kind: str
    error: str | None = None


@dataclass
class EntityMigrationResult:
    """Result of migrating one entity."""

    entity_id: str
    files: list[FileMigrationResult] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None

    @property
    def encrypted_count(self) -> int:
        return sum(1 for f in self.files if f.action == "encrypted")

    @property
    def re_encrypted_count(self) -> int:
        return sum(1 for f in self.files if f.action == "re-encrypted")

    @property
    def skipped_v2_count(self) -> int:
        return sum(1 for f in self.files if f.action == "skipped-v2")

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.files if f.action == "error")


@dataclass
class MigrationSummary:
    """Content-free summary of the full migration."""

    dry_run: bool
    results: list[EntityMigrationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _sha256(data: bytes) -> str:
    """Hex digest of data."""
    return hashlib.sha256(data).hexdigest()


def _kind_for_file(rel_path: str) -> str:
    """Determine the v2 envelope kind from a file's relative path within an entity dir."""
    parts = Path(rel_path).parts
    name = Path(rel_path).name

    if name == "snapshot.json":
        return "snapshot"
    if len(parts) >= 1 and parts[0] == "artifacts":
        return "artifact"
    if name in ("bundle.tar.enc", "bundle.tar"):
        return "bundle"
    if name.endswith(".jsonl"):
        return "sidecar-jsonl"
    if len(parts) >= 1 and parts[0] == "world_model":
        return "world_model"
    if len(parts) >= 1 and parts[0] == "self_model":
        return "self_model"

    # Default to artifact for files inside snapshot dirs, bundle for preservation
    return "artifact"


def _discover_entities(state_root: Path) -> list[tuple[str, Path, str]]:
    """Walk state_root and discover entities.

    Returns a list of (entity_id, entity_dir, source_type) tuples where
    source_type is "snapshot" or "preservation".
    """
    entities: list[tuple[str, Path, str]] = []

    # Snapshot directories: state/<snapshot_id>/snapshot.json
    for entry in sorted(state_root.iterdir()) if state_root.is_dir() else []:
        if entry.name.startswith(".") or entry.name == "identity":
            continue
        snap_file = entry / "snapshot.json"
        if entry.is_dir() and snap_file.is_file():
            entity_id = _entity_id_from_snapshot(snap_file)
            if entity_id:
                entities.append((entity_id, entry, "snapshot"))
            else:
                log.warning("no entity_id in %s; skipping", snap_file)

    # Preservation bundles: state/preservation/<entity_id>/
    pres_root = state_root / "preservation"
    if pres_root.is_dir():
        for entry in sorted(pres_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                entity_id = _entity_id_from_preservation(entry)
                if entity_id:
                    entities.append((entity_id, entry, "preservation"))
                else:
                    log.warning(
                        "cannot determine entity_id for preservation dir %s; skipping",
                        entry,
                    )

    return entities


def _entity_id_from_snapshot(snap_file: Path) -> str | None:
    """Extract entity_id from a snapshot.json.

    Tries the metadata.identity.entity_id field first, then the identity
    sidecar beside it.
    """
    try:
        raw = snap_file.read_bytes()
        # The file may be v1-encrypted, v2-encrypted, or plaintext.
        # Try to read it as plaintext JSON first; if that fails and it looks
        # encrypted we cannot get the entity_id without the key, so fall back
        # to the sidecar.
        text = raw.decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                md = data.get("metadata", {})
                if isinstance(md, dict):
                    identity = md.get("identity", {})
                    if isinstance(identity, dict):
                        eid = identity.get("entity_id")
                        if isinstance(eid, str) and eid:
                            return eid
        except (json.JSONDecodeError, ValueError):
            pass  # not JSON; fall through to sidecar
    except OSError:
        pass  # snapshot file unreadable; fall through to sidecar

    # Fall back to identity sidecar
    sidecar = snap_file.parent / "identity.json"
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text())
            eid = data.get("entity_id")
            if isinstance(eid, str) and eid:
                return eid
        except (OSError, json.JSONDecodeError, ValueError):
            pass  # sidecar unreadable; give up

    return None


def _entity_id_from_preservation(pres_dir: Path) -> str | None:
    """Extract entity_id from a preservation directory.

    Tries manifest.json first, then the directory name if it matches
    the entity_id format.
    """
    manifest = pres_dir / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text())
            if isinstance(data, dict):
                identity = data.get("identity", {})
                if isinstance(identity, dict):
                    eid = identity.get("entity_id")
                    if isinstance(eid, str) and eid:
                        return eid
        except (OSError, json.JSONDecodeError, ValueError):
            pass  # manifest unreadable or malformed; try directory name

    # The directory name may be the entity_id
    import re

    if re.fullmatch(r"(ent|legacy)-[0-9a-f]{32}", pres_dir.name):
        return pres_dir.name

    return None


def _backup_entity(entity_dir: Path, backup_root: Path) -> Path:
    """Copy entity_dir to backup_root, preserving structure.

    Returns the backup directory path.
    """
    backup_dir = backup_root / entity_dir.name
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.copytree(entity_dir, backup_dir, symlinks=False)
    return backup_dir


def _collect_files(entity_dir: Path) -> list[Path]:
    """Collect all regular files under entity_dir, excluding identity sidecars."""
    files: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(entity_dir, followlinks=False):
        for filename in sorted(filenames):
            filepath = Path(dirpath) / filename
            if filepath.is_symlink():
                continue
            # Skip identity sidecars and manifest.json (plaintext metadata)
            if filename in ("identity.json", "manifest.json"):
                continue
            files.append(filepath)
    return files


def _atomic_write(path: Path, data: bytes) -> None:
    """Write data to path atomically via a temp file and os.replace."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.mig.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            os.chmod(tmp, 0o600)
        except (OSError, NotImplementedError):
            pass  # best-effort; fd already opened 0o600
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # cleanup must not mask the original error
        raise


def _migrate_file(
    filepath: Path,
    entity_dir: Path,
    entity_id: str,
    v1_decryptor: StateEncryptor,
    encryptor: object,
    *,
    dry_run: bool,
) -> FileMigrationResult:
    """Migrate a single file from v1/plaintext to v2.

    Returns a content-free result describing what was done.
    """
    rel_path = str(filepath.relative_to(entity_dir))
    kind = _kind_for_file(rel_path)

    if kind not in VALID_KINDS:
        kind = "artifact"

    raw = filepath.read_bytes()

    # Already v2: skip
    if is_v2(raw):
        return FileMigrationResult(path=rel_path, action="skipped-v2", kind=kind)

    # Determine plaintext
    if is_encrypted(raw):
        # v1 encrypted: decrypt with operator key
        plaintext = v1_decryptor.decrypt(raw)
        action = "re-encrypted"
    else:
        # Check if it's base64-encoded v1
        try:
            import base64

            decoded = base64.b64decode(raw, validate=True)
            if is_encrypted(decoded):
                plaintext = v1_decryptor.decrypt(raw)
                action = "re-encrypted"
            else:
                plaintext = raw
                action = "encrypted"
        except Exception:
            plaintext = raw
            action = "encrypted"

    if dry_run:
        return FileMigrationResult(path=rel_path, action=action, kind=kind)

    # Re-encrypt under entity DEK with v2 envelope
    v2_blob = encryptor.encrypt(plaintext, kind=kind)

    # Verify: decrypt and compare hash
    roundtrip = encryptor.decrypt(v2_blob, kind=kind)
    if _sha256(roundtrip) != _sha256(plaintext):
        return FileMigrationResult(
            path=rel_path,
            action="error",
            kind=kind,
            error="verify-after-encrypt failed: hash mismatch",
        )

    # Atomic write
    _atomic_write(filepath, v2_blob)

    return FileMigrationResult(path=rel_path, action=action, kind=kind)


def _migrate_entity(
    entity_id: str,
    entity_dir: Path,
    keyring: KeyRing,
    v1_decryptor: StateEncryptor,
    backup_root: Path,
    *,
    dry_run: bool,
    force: bool,
) -> EntityMigrationResult:
    """Migrate all files for one entity."""
    result = EntityMigrationResult(entity_id=entity_id)

    # Check if DEK already exists
    if keyring.has_dek(entity_id) and not force:
        result.skipped = True
        result.error = "DEK already exists (use --force to re-migrate)"
        log.info("skipping %s: DEK already exists", entity_id)
        return result

    files = _collect_files(entity_dir)
    if not files:
        log.info("no files to migrate for %s", entity_id)
        return result

    # Back up before any modification
    if not dry_run:
        log.info("backing up %s", entity_id)
        _backup_entity(entity_dir, backup_root)

    # Generate DEK (or load existing if --force)
    encryptor = None
    if not dry_run:
        if keyring.has_dek(entity_id):
            encryptor = keyring.encryptor_for(entity_id)
        else:
            keyring.generate_dek(entity_id)
            encryptor = keyring.encryptor_for(entity_id)

    for filepath in files:
        try:
            if dry_run:
                # In dry run, simulate the detection without an encryptor
                file_result = _dry_run_detect(filepath, entity_dir, v1_decryptor)
            else:
                file_result = _migrate_file(
                    filepath,
                    entity_dir,
                    entity_id,
                    v1_decryptor,
                    encryptor,
                    dry_run=False,
                )
            result.files.append(file_result)
        except Exception as exc:
            result.files.append(
                FileMigrationResult(
                    path=str(filepath.relative_to(entity_dir)),
                    action="error",
                    kind=_kind_for_file(str(filepath.relative_to(entity_dir))),
                    error=str(exc),
                )
            )
            log.error("error migrating %s: %s", filepath, exc)

    return result


def _dry_run_detect(
    filepath: Path,
    entity_dir: Path,
    v1_decryptor: StateEncryptor,
) -> FileMigrationResult:
    """Detect what would happen to a file without writing anything."""
    rel_path = str(filepath.relative_to(entity_dir))
    kind = _kind_for_file(rel_path)
    if kind not in VALID_KINDS:
        kind = "artifact"

    raw = filepath.read_bytes()

    if is_v2(raw):
        return FileMigrationResult(path=rel_path, action="skipped-v2", kind=kind)

    if is_encrypted(raw):
        return FileMigrationResult(path=rel_path, action="re-encrypted", kind=kind)

    try:
        import base64

        decoded = base64.b64decode(raw, validate=True)
        if is_encrypted(decoded):
            return FileMigrationResult(path=rel_path, action="re-encrypted", kind=kind)
    except Exception:
        pass

    return FileMigrationResult(path=rel_path, action="encrypted", kind=kind)


def migrate(
    state_root: str | Path = "state",
    *,
    dry_run: bool = False,
    force: bool = False,
    kek: KekProvider | None = None,
) -> MigrationSummary:
    """Run the one-way migration from v1/plaintext to per-entity v2 encryption.

    Parameters
    ----------
    state_root:
        Path to the state root directory (default ``"state"``).
    dry_run:
        When ``True``, report what would be done without writing any files.
    force:
        When ``True``, re-migrate entities that already have a DEK.
    kek:
        Optional KEK provider. When ``None``, a ``SoftwareKek`` is built from
        the ``KAINE_CUSTODY_KEK`` environment variable, falling back to a key
        derived from ``KAINE_STATE_KEY``.

    Returns
    -------
    MigrationSummary
        A content-free summary of the migration.

    Raises
    ------
    MigrationError
        When the migration cannot proceed.
    """
    from kaine.storage import resolve

    root = resolve(state_root)
    summary = MigrationSummary(dry_run=dry_run)

    if not root.is_dir():
        raise MigrationError(f"state root does not exist: {root}")

    # Set up v1 decryptor (the operator key)
    try:
        v1_config = CryptoConfig(enabled=True)
        v1_decryptor = StateEncryptor(v1_config)
    except Exception as exc:
        raise MigrationError(
            f"cannot set up v1 decryptor (is KAINE_STATE_KEY set?): {exc}"
        ) from exc

    # Set up the KEK for wrapping new DEKs
    if kek is None:
        kek = _default_kek()

    keyring = KeyRing(kek, state_root=root)

    # Discover entities
    entities = _discover_entities(root)
    if not entities:
        log.info("no entities found in %s", root)
        return summary

    log.info("found %d entities to migrate", len(entities))

    # Set up backup root
    backup_root = root / ".migration-backup"
    if not dry_run:
        backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Migrate each entity
    for entity_id, entity_dir, source_type in entities:
        log.info("migrating entity %s (%s) at %s", entity_id, source_type, entity_dir)
        try:
            result = _migrate_entity(
                entity_id,
                entity_dir,
                keyring,
                v1_decryptor,
                backup_root,
                dry_run=dry_run,
                force=force,
            )
            summary.results.append(result)
        except Exception as exc:
            error_msg = f"failed to migrate entity {entity_id}: {exc}"
            log.error("%s", error_msg)
            summary.errors.append(error_msg)
            summary.results.append(
                EntityMigrationResult(entity_id=entity_id, error=error_msg)
            )

    return summary


def _default_kek() -> KekProvider:
    """Build a default KEK from the environment."""
    from kaine.security.custody.keyring import SoftwareKek

    # Try KAINE_CUSTODY_KEK first (hex-encoded 32 bytes, matching build_keyring)
    kek_raw = os.environ.get("KAINE_CUSTODY_KEK")
    if kek_raw:
        try:
            kek_bytes = bytes.fromhex(kek_raw.strip())
        except ValueError as exc:
            raise MigrationError(
                f"KAINE_CUSTODY_KEK is not valid hex: {exc}"
            ) from exc
        return SoftwareKek(kek_bytes)

    # Fall back to KAINE_STATE_KEY (the operator key serves as KEK during migration)
    state_key_raw = os.environ.get("KAINE_STATE_KEY")
    if state_key_raw:
        # Derive a KEK from the state key so it is distinct
        import hashlib

        derived = hashlib.sha256(b"kaine/migration-kek|" + state_key_raw.encode()).digest()
        return SoftwareKek(derived)

    raise MigrationError(
        "no KEK available: set KAINE_CUSTODY_KEK or KAINE_STATE_KEY"
    )
