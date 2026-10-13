# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare-gated entity decommission: transferable backup + state deletion.

This module implements the two destructive primitives the decommission CLI
(:mod:`kaine.lifecycle.__main__`) orchestrates:

* :func:`capture_backup` — produce ``backups/entity_<name>_<utc>/``: the
  entity's transferable self (self-model, the language module's intent log, the sleep module's
  voice adapters, world-model weight checkpoints, the latest fork
  snapshot, a best-effort Qdrant export of the
  episodic memory and social cognition modules' collections) plus a ``manifest.json`` recording the
  divergence assessment, the continuity note, the file inventory, and restore
  notes. The bundle is encrypted with the existing state encryptor when state
  encryption is enabled. This satisfies CAL 4.2(b) ("saving the Entity's
  complete Cognitive State in a format that allows it to be restarted
  elsewhere"). Backup is **blocking**: a failure must abort decommission.

* :func:`delete_entity_state` — remove the on-disk state subtrees, drop the
  episodic memory and social cognition modules' Qdrant collections, and clear entity Redis streams. It only
  ever operates under the provided ``state_root`` (so tests can point it at a
  tmp dir) and supports ``dry_run`` (report what *would* be removed).

Nothing here starts or stops the entity; decommission runs against a STOPPED
entity. The ``ForkManager`` is used only to locate and copy the latest existing
snapshot file — never to take a new snapshot (there is no live registry).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine import legacy_aliases
from kaine.bus.config import load_secrets_doc
from kaine.lifecycle.decommission_locations import (
    BACKUP_DELETE,
    DELETE,
    RETAIN,
    checkpoint_sqlite,
    entity_locations,
    read_snapshot_json,
)
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.identity import IdentityError, load_identity
from kaine.memory_kinds import (
    EPISODIC_MEMORY_COLLECTION_KINDS,
    EPISODIC_MEMORY_STAMP_COLLECTION,
    stamp_key,
    stamp_point_id,
    strength_key,
)
from kaine.storage import resolve

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class BackupResult:
    """Outcome of :func:`capture_backup`."""

    ok: bool
    backup_path: Path
    manifest_path: Path | None = None
    encrypted: bool = False
    encryption_failed: bool = False
    inventory: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # Set when the bundle was produced from a LIVE registry (preserve_live):
    # the id of the snapshot taken of the live modules so revive can locate it.
    live_snapshot_id: str | None = None


@dataclass
class DeleteResult:
    """Outcome of :func:`delete_entity_state`."""

    dry_run: bool
    removed_paths: list[str] = field(default_factory=list)
    would_remove_paths: list[str] = field(default_factory=list)
    dropped_collections: list[str] = field(default_factory=list)
    cleared_redis_streams: list[str] = field(default_factory=list)
    skipped_non_streams: list[str] = field(default_factory=list)
    redis_failed: str | None = None
    aof_rewrite: str | None = None
    rdb_snapshot: str | None = None
    deleted_locations: list[str] = field(default_factory=list)
    retained_locations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_name(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (name or "entity"))
    return cleaned or "entity"


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        # e.g. no chmod support on this platform, or a permission error on an
        # already-owner-only file; the caller's hardening is best-effort.
        pass


def _harden_tree(root: Path) -> None:
    """Recursively set owner-only perms on a bundle: dirs 0700, files 0600.

    Bundle content is entity-interior cognitive state and must not be group- or
    world-readable. ``shutil.copy2`` preserves source perms (often 0644); this
    re-hardens everything copied in.
    """
    _chmod_quietly(root, 0o700)
    for child in root.rglob("*"):
        _chmod_quietly(child, 0o700 if child.is_dir() else 0o600)


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp gives 0600 on the tmp, but os.replace onto an existing target
        # inherits the existing file's perms; chmod the tmp BEFORE replace so the
        # final file is owner-only regardless of any pre-existing target perms.
        _chmod_quietly(Path(tmp_name), mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            # Cleanup of our own tempfile; already gone is fine (e.g. the
            # failure happened before mkstemp's fd was fully materialized as
            # a path on this filesystem). The original error is re-raised
            # below regardless.
            pass
        raise


def _write_sensitive_sidecar(path: Path, plaintext_json: str) -> None:
    """Write a sensitive sidecar, encrypting via StateEncryptor when enabled.

    When state encryption is enabled the content is encrypted in place (an
    encrypted blob that later rides inside the encrypted tar — defence in depth).
    When disabled it is written as honest plaintext to a clearly-named separate
    sidecar (never folded into the manifest), so the operator can choose how to
    handle it. Files are written owner-only (0600).
    """
    try:
        from kaine.security.crypto import get_state_encryptor

        text = get_state_encryptor().encrypt_text(plaintext_json)
    except Exception:
        # Encryptor unavailable/misconfigured → honest plaintext (the bundle-tar
        # encryption step still wraps it when enabled; if that fails the whole
        # bundle is purged by the encryption-failure path).
        text = plaintext_json
    _atomic_write_text(path, text, mode=0o600)


def _purge_plaintext_bundle(bundle_dir: Path, *, error: str) -> None:
    """Remove all plaintext bundle artifacts, leaving only an error marker.

    Called when encryption was requested but FAILED: no plaintext entity content
    (self-model, intent monologue, snapshot, sidecars, manifest) may linger.
    """
    for child in list(bundle_dir.iterdir()):
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        except OSError:
            log.warning("could not remove plaintext artifact %s", child, exc_info=True)
    try:
        _atomic_write_text(
            bundle_dir / "ENCRYPTION_FAILED.txt",
            "Bundle encryption was enabled but FAILED; all plaintext entity "
            "artifacts were removed so no plaintext entity content lingers on "
            "disk. Decommission was aborted (no state deleted). Resolve the "
            f"encryption error and re-run the backup.\n\nError: {error}\n",
            mode=0o600,
        )
    except Exception:
        log.warning("could not write encryption-failure marker", exc_info=True)


def _episodic_memory_prefix(qdrant_cfg: dict[str, Any] | None) -> str:
    cfg = qdrant_cfg or {}
    return str((cfg.get("mnemos") or {}).get("collection_prefix", "mnemos_"))


def _episodic_memory_collection_names(qdrant_cfg: dict[str, Any] | None) -> list[str]:
    cfg = qdrant_cfg or {}
    prefix = _episodic_memory_prefix(cfg)
    names = [f"{prefix}{kind}" for kind in EPISODIC_MEMORY_COLLECTION_KINDS]
    social_cognition = str((cfg.get("empatheia") or {}).get("collection", "empatheia_agents"))
    if social_cognition:
        names.append(social_cognition)
    return names


def _qdrant_client(qdrant_cfg: dict[str, Any] | None):
    """Build a QdrantClient from a connection config dict, or None on failure.

    ``qdrant_cfg`` mirrors the kaine.toml layout: the connection lives at
    ``[mnemos.qdrant]`` (host/port/api_key). A flat ``{host, port, api_key}``
    dict is also accepted for tests.
    """
    cfg = qdrant_cfg or {}
    conn = (cfg.get("mnemos") or {}).get("qdrant") or cfg.get("connection") or cfg
    host = str(conn.get("host", "127.0.0.1"))
    port = int(conn.get("port", 6533))
    api_key = conn.get("api_key") or None
    try:
        from qdrant_client import QdrantClient

        return QdrantClient(host=host, port=port, api_key=api_key, timeout=10.0)
    except Exception:
        log.debug("capture_backup: could not construct QdrantClient", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _export_qdrant(
    client,
    collections: list[str],
    out_dir: Path,
) -> tuple[list[str], list[str]]:
    """Scroll each collection to a JSONL file. Returns (written, errors).

    Best-effort: any failure is recorded as an error string; never raises.
    """
    written: list[str] = []
    errors: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for coll in collections:
        try:
            offset = None
            lines: list[str] = []
            while True:
                points, offset = client.scroll(
                    collection_name=coll,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for p in points:
                    lines.append(
                        json.dumps(
                            {
                                "id": getattr(p, "id", None),
                                "payload": getattr(p, "payload", None),
                                "vector": getattr(p, "vector", None),
                            },
                            default=str,
                        )
                    )
                if offset is None:
                    break
            target = out_dir / f"{coll}.jsonl"
            _atomic_write_text(target, "\n".join(lines) + ("\n" if lines else ""))
            written.append(f"qdrant/{coll}.jsonl ({len(lines)} points)")
        except Exception as exc:
            errors.append(f"qdrant collection {coll!r}: {type(exc).__name__}: {exc}")
            log.debug("capture_backup: qdrant export failed for %s", coll, exc_info=True)
    return written, errors


def qdrant_in_use(config: Mapping[str, Any] | None) -> bool:
    """Return True when episodic or social memory uses the Qdrant backend.

    Follows the runtime's own defaults (``kaine.extras``): a ``[mnemos]`` or
    ``[empatheia]`` section without a ``backend`` key, or no section at all,
    means Qdrant. Treating a missing key as "not used" would skip the export
    and the deletion of a store the cycle actually wrote to.
    """
    cfg = config or {}
    for section_name in ("mnemos", "empatheia"):
        section = cfg.get(section_name)
        if not isinstance(section, Mapping):
            section = {}
        if section.get("backend", "qdrant") == "qdrant":
            return True
    return False


def with_qdrant_api_key(
    config: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str] | None = None,
    secrets_path: Path | None = None,
) -> dict[str, Any]:
    """Return a deep copy of *config* with Qdrant API keys folded in.

    Keys are filled from ``env["KAINE_QDRANT_API_KEY"]`` or the secrets doc,
    only when the section already has a ``qdrant`` sub-table and no ``api_key``.
    Empty values are never injected.
    """
    import copy

    result: dict[str, Any] = copy.deepcopy(config) if config is not None else {}
    env = os.environ if env is None else env
    key: str | None = env.get("KAINE_QDRANT_API_KEY")
    if key is None:
        key = load_secrets_doc(secrets_path).get("qdrant", {}).get("api_key")
    if not key:
        return result
    for section_name in ("mnemos", "empatheia"):
        section = result.get(section_name)
        if not isinstance(section, dict):
            continue
        qdrant_cfg = section.get("qdrant")
        if not isinstance(qdrant_cfg, dict) or qdrant_cfg.get("api_key"):
            continue
        qdrant_cfg["api_key"] = key
    return result


def _bundle_relpath(
    path: Path, *, state_root: Path, data_root: Path, fork_root: Path
) -> Path:
    """Return the relative path under which *path* is stored in a backup bundle."""
    try:
        return path.relative_to(state_root)
    except ValueError:
        pass
    try:
        return Path("data") / path.relative_to(data_root)
    except ValueError:
        pass
    try:
        return Path("forks") / path.relative_to(fork_root)
    except ValueError:
        pass
    return Path(path.name)


def capture_backup(
    *,
    state_root: Path,
    fork_root: Path,
    data_root: Path | None = None,
    qdrant_cfg: dict[str, Any] | None,
    out_root: Path = Path("backups"),
    entity_name: str,
    assessment: DivergenceAssessment,
    continuity_note: str | None = None,
) -> BackupResult:
    """Produce a transferable backup bundle. Blocking; caller aborts on failure.

    See the module docstring for what is captured. Returns a :class:`BackupResult`
    with ``ok=False`` (and populated ``errors``) when the bundle could not be
    assembled — the CLI then aborts without deleting anything.
    """
    state_root = resolve(state_root)
    out_root = resolve(out_root)
    fork_root = resolve(fork_root)
    data_root = resolve(data_root) if data_root is not None else state_root.parent / "data"
    inventory: list[str] = []
    errors: list[str] = []

    bundle_dir = out_root / f"entity_{_safe_name(entity_name)}_{_utc_stamp()}"
    # The entity's identity goes into the plaintext manifest so key custody can
    # find its key without decrypting the bundle (entity-identity D7). It is read
    # before the bundle directory exists, so an unreadable identity leaves no
    # partial copy of the entity behind (D10).
    identity_entry: dict[str, Any] | None = None
    try:
        identity = load_identity(state_root / "identity" / "entity.json")
    except IdentityError as exc:
        return BackupResult(
            ok=False,
            backup_path=bundle_dir,
            errors=[f"load identity for backup: {exc}"],
        )
    if identity is not None:
        identity_entry = {
            "entity_id": identity.entity_id,
            "lineage": list(identity.lineage),
        }
    try:
        # out_root may not exist yet; create it owner-only too.
        out_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _chmod_quietly(out_root, 0o700)
        bundle_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        _chmod_quietly(bundle_dir, 0o700)
    except Exception as exc:
        return BackupResult(
            ok=False,
            backup_path=bundle_dir,
            errors=[f"could not create backup dir: {type(exc).__name__}: {exc}"],
        )

    # Fold in Qdrant authentication so the backup can reach the same server
    # the running cycle uses.
    qdrant_cfg = with_qdrant_api_key(qdrant_cfg)
    entity_id = identity.entity_id if identity is not None else None
    locations = entity_locations(
        qdrant_cfg,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        entity_id=entity_id,
    )

    # --- 1. Self-model ------------------------------------------
    self_model_src = state_root / "eidolon" / "self_model.json"
    if self_model_src.is_file():
        try:
            shutil.copy2(self_model_src, bundle_dir / "self_model.json")
            inventory.append("self_model.json")
        except Exception as exc:
            return BackupResult(
                ok=False,
                backup_path=bundle_dir,
                errors=[f"copy self_model.json: {exc}"],
            )

    # --- 2. Language intent expression log --------------------------------
    intent_src = state_root / "lingua" / "intent_expression.jsonl"
    if intent_src.is_file():
        try:
            shutil.copy2(intent_src, bundle_dir / "intent_expression.jsonl")
            inventory.append("intent_expression.jsonl")
        except Exception as exc:
            return BackupResult(
                ok=False,
                backup_path=bundle_dir,
                errors=[f"copy intent_expression.jsonl: {exc}"],
            )

    # --- 2b. Rotated intent log corpus ----------------------------------
    intent_corpus_src = state_root / "lingua" / "intent_log"
    if intent_corpus_src.is_dir():
        try:
            shutil.copytree(
                intent_corpus_src, bundle_dir / "intent_log", dirs_exist_ok=True
            )
            inventory.append("intent_log/")
        except Exception as exc:
            return BackupResult(
                ok=False,
                backup_path=bundle_dir,
                errors=[f"copy intent_log/: {exc}"],
            )

    # Sleep voice adapters are copied by the generic "sleep.adapters" location step.

    # World-model checkpoints are copied by the generic "world_model" location step.

    # --- 4a. Individuation evidence ---------------------------------------
    # Maturation reference, ledger, reports and stored maturation adapter. This evidence
    # travels with the entity into the backup and is included in the same
    # tar/encryption pass as the other subtrees. A failure here is fatal: the
    # CLI must not delete the only copy of the evidence.
    individuation_src = state_root / "individuation"
    if individuation_src.is_dir():
        try:
            shutil.copytree(
                individuation_src,
                bundle_dir / "individuation",
                dirs_exist_ok=True,
            )
            inventory.append("individuation/")
        except Exception as exc:
            return BackupResult(
                ok=False,
                backup_path=bundle_dir,
                errors=[f"could not copy individuation evidence: {type(exc).__name__}: {exc}"],
            )

    # --- 5. Latest fork snapshot ----------------------------------------
    # Only snapshots attributed to this entity are eligible.
    latest_snapshot_id: str | None = None
    own_location = next((loc for loc in locations if loc.key == "forks.own"), None)
    if own_location is not None:
        best_ts = None
        for snap_dir in own_location.existing():
            if not snap_dir.is_dir():
                continue
            snap_data = read_snapshot_json(snap_dir)
            if snap_data is None:
                continue
            ts = snap_data.get("timestamp")
            if ts is None:
                continue
            if best_ts is None or ts >= best_ts:
                best_ts, latest_snapshot_id = ts, snap_dir.name
        if latest_snapshot_id is not None:
            src = fork_root / latest_snapshot_id / "snapshot.json"
            if src.is_file():
                try:
                    shutil.copy2(src, bundle_dir / "snapshot.json")
                    inventory.append(f"snapshot.json (fork {latest_snapshot_id})")
                except Exception as exc:
                    errors.append(f"copy latest fork snapshot: {exc}")

    # --- 6. Backup every location marked for backup+delete -------------
    for loc in locations:
        if loc.decision != BACKUP_DELETE or loc.bundle_dir is None:
            continue
        # Checkpoint SQLite stores before copying so the backup is internally
        # consistent and can be opened without the -wal file.
        if loc.key == "episodic_memory.sqlite":
            for path in loc.existing():
                if path.name.endswith("-wal") or path.name.endswith("-shm"):
                    continue
                checkpoint_error = checkpoint_sqlite(path)
                if checkpoint_error is not None:
                    return BackupResult(
                        ok=False,
                        backup_path=bundle_dir,
                        errors=[f"checkpoint SQLite for {loc.key}: {checkpoint_error}"],
                    )
        copied_any = False
        for path in loc.existing():
            rel = _bundle_relpath(
                path, state_root=state_root, data_root=data_root, fork_root=fork_root
            )
            dest = bundle_dir / loc.bundle_dir / rel
            try:
                if path.is_dir():
                    shutil.copytree(path, dest, symlinks=True, dirs_exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                copied_any = True
            except Exception as exc:
                return BackupResult(
                    ok=False,
                    backup_path=bundle_dir,
                    errors=[f"back up {loc.key}: {type(exc).__name__}: {exc}"],
                )
        if copied_any:
            inventory.append(f"{loc.bundle_dir}/ ({loc.key})")

    # --- 7. Qdrant export -----------------------------------------------
    qdrant_status = "exported"
    if not qdrant_in_use(qdrant_cfg):
        inventory.append("qdrant: not used by this deployment")
        qdrant_status = "not used"
    else:
        client = _qdrant_client(qdrant_cfg)
        if client is None:
            return BackupResult(
                ok=False,
                backup_path=bundle_dir,
                errors=["qdrant: cannot reach or authenticate to Qdrant; nothing was deleted"],
            )
        try:
            try:
                existing_collections = {c.name for c in client.get_collections().collections}
            except Exception:
                return BackupResult(
                    ok=False,
                    backup_path=bundle_dir,
                    errors=["qdrant: cannot reach or authenticate to Qdrant; nothing was deleted"],
                )
            collections = [
                c for c in _episodic_memory_collection_names(qdrant_cfg) if c in existing_collections
            ]
            qdrant_dir = bundle_dir / "qdrant"
            qdrant_written, qdrant_errors = _export_qdrant(client, collections, qdrant_dir)
            if qdrant_errors:
                return BackupResult(
                    ok=False,
                    backup_path=bundle_dir,
                    errors=qdrant_errors,
                )
            inventory.extend(qdrant_written)
        finally:
            try:
                client.close()
            except Exception:
                log.debug("capture_backup: qdrant client close failed", exc_info=True)

    # --- 7. Sensitive sidecars (entity inner-life / individuation evidence) --
    # The entity's expressed continuity view (``continuity_note``) and the full
    # individuation/divergence evidence (``assessment.signals`` + summary) are
    # entity-interior content. They must NOT sit in the plaintext manifest. They
    # are written to separate ``continuity.json`` / ``assessment.json`` sidecars
    # which ride INSIDE the encrypted tar when encryption is enabled, and are
    # honestly-plaintext separate sidecars when it is disabled (the operator can
    # then choose how to handle them). The continuity note is collected by the
    # CLI AFTER this backup completes, so ``continuity.json`` is (re)written via
    # ``update_manifest_continuity_note`` — encrypted in place when enabled.
    assessment_sidecar = {
        "diverged": assessment.diverged,
        "signals": assessment.signals,
        "summary": assessment.summary,
    }
    try:
        _write_sensitive_sidecar(
            bundle_dir / "assessment.json",
            json.dumps(assessment_sidecar, indent=2, sort_keys=True),
        )
        inventory.append("assessment.json (sensitive: individuation evidence)")
    except Exception as exc:
        errors.append(f"write assessment.json: {exc}")
    if continuity_note is not None:
        try:
            _write_sensitive_sidecar(
                bundle_dir / "continuity.json",
                json.dumps({"continuity_note": continuity_note}, indent=2),
            )
            inventory.append("continuity.json (sensitive: continuity note)")
        except Exception as exc:
            errors.append(f"write continuity.json: {exc}")

    # --- 8. Manifest (NON-sensitive inventory only) ---------------------
    manifest = {
        "entity_name": entity_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # Bare divergence bool only — the p-values/drift counts live in the
        # (encrypted) assessment.json sidecar, never here.
        "diverged": assessment.diverged,
        "inventory": inventory,
        "qdrant": qdrant_status,
        "locations": [
            {"key": loc.key, "decision": loc.decision, "present": bool(loc.existing())}
            for loc in locations
        ],
        "restore_notes": (
            "This bundle preserves the entity's transferable cognitive state per "
            "CAL Article 4.2(b). The complete state is under locations/<key>/, with paths "
            "relative to the state root, the data root (data/) or the fork root (forks/): "
            "to restore on another host, copy each back to the same place (for example "
            "locations/world_model/phantasia/ to state/phantasia/ and "
            "locations/sleep.adapters/hypnos/adapters/ to state/hypnos/adapters/), "
            "restore individuation/ to state/individuation/, and re-import the "
            "qdrant/*.jsonl exports before booting. self_model.json, intent_expression.jsonl "
            "and snapshot.json at the top level are convenience copies of the same state. "
            "Sensitive entity inner-life (continuity.json, assessment.json) is kept out "
            "of this manifest; with state encryption enabled it rides inside bundle.tar.enc, "
            "so decrypt it with the operator's KAINE_STATE_KEY first."
        ),
    }
    if identity_entry is not None:
        manifest["identity"] = identity_entry

    manifest_path = bundle_dir / "manifest.json"
    try:
        _atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
    except Exception as exc:
        return BackupResult(
            ok=False,
            backup_path=bundle_dir,
            inventory=inventory,
            errors=errors + [f"write manifest.json: {exc}"],
        )

    # Re-harden perms on everything copied/written so far (copy2 preserves
    # source perms, often 0644). Dirs → 0700, files → 0600.
    _harden_tree(bundle_dir)

    # --- 9. Encrypt the bundle when state encryption is enabled ---------
    encrypted = False
    try:
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()
        if encryptor.enabled:
            # Tar the captured artifacts (INCLUDING the sensitive sidecars;
            # EXCLUDING the manifest, which stays readable so an operator can
            # inspect the non-sensitive inventory without the key) then encrypt
            # the tar bytes.
            tar_bytes_path = bundle_dir / "_bundle.tar"
            with tarfile.open(tar_bytes_path, "w") as tar:
                for child in sorted(bundle_dir.iterdir()):
                    if child.name in ("_bundle.tar", "manifest.json"):
                        continue
                    tar.add(child, arcname=child.name)
            raw = tar_bytes_path.read_bytes()
            blob = encryptor.encrypt(raw)  # bytes in, base64 bytes out
            _atomic_write_text(bundle_dir / "bundle.tar.enc", blob.decode("ascii"))
            # Remove the now-encrypted plaintext artifacts.
            tar_bytes_path.unlink()
            for child in list(bundle_dir.iterdir()):
                if child.name in ("bundle.tar.enc", "manifest.json"):
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError as exc:
                        # This artifact's content is now also inside
                        # bundle.tar.enc, but leaving the plaintext copy
                        # behind after we report "encrypted" would violate
                        # CAL 4.3 (no lingering plaintext entity content).
                        # Surface it as a backup error so the operator sees it.
                        log.warning(
                            "could not remove plaintext artifact %s after "
                            "encrypting the bundle; unencrypted entity content "
                            "may remain on disk",
                            child,
                            exc_info=True,
                        )
                        errors.append(
                            f"could not remove plaintext {child.name} after "
                            f"encryption: {exc}"
                        )
                if child.exists():
                    # A partial removal leaves plaintext entity content at rest
                    # next to the encrypted archive; this is not a valid backup.
                    return BackupResult(
                        ok=False,
                        backup_path=bundle_dir,
                        manifest_path=None,
                        encrypted=False,
                        encryption_failed=True,
                        inventory=inventory,
                        errors=errors + [
                            f"could not remove plaintext {child.name} after "
                            f"encrypting the backup; unencrypted content remains"
                        ],
                    )
            encrypted = True
            inventory.append("bundle.tar.enc (encrypted)")
            # Refresh manifest inventory to reflect the encrypted layout.
            manifest["inventory"] = inventory
            manifest["encrypted"] = True
            _atomic_write_text(
                manifest_path, json.dumps(manifest, indent=2, sort_keys=True)
            )
            _harden_tree(bundle_dir)
    except Exception as exc:
        # Encryption was enabled and FAILED: a plaintext bundle now exists on
        # disk while the operator requested an encrypted backup.  This is a
        # security downgrade — the operator may delete entity state believing an
        # encrypted backup exists.  Actively REMOVE the plaintext entity content
        # (incl. intent_expression.jsonl internal monologue) and leave only an
        # error marker, then report failure so the CLI aborts deletion.
        errors.append(f"bundle encryption: {type(exc).__name__}: {exc}")
        log.error(
            "capture_backup: bundle encryption failed at %s — removing plaintext "
            "entity artifacts and reporting ok=False so decommission does not "
            "proceed and no plaintext entity content lingers",
            bundle_dir,
            exc_info=True,
        )
        _purge_plaintext_bundle(
            bundle_dir, error=f"{type(exc).__name__}: {exc}"
        )
        return BackupResult(
            ok=False,
            backup_path=bundle_dir,
            manifest_path=None,
            encrypted=False,
            encryption_failed=True,
            inventory=inventory,
            errors=errors,
        )

    return BackupResult(
        ok=True,
        backup_path=bundle_dir,
        manifest_path=manifest_path,
        encrypted=encrypted,
        inventory=inventory,
        errors=errors,
    )


def update_manifest_continuity_note(backup: BackupResult, note: str) -> bool:
    """Record the entity's continuity note as a sensitive sidecar. Guarded.

    The continuity note is collected by the CLI AFTER ``capture_backup`` finishes
    (and after any bundle encryption sealed the tar), so it cannot ride inside the
    encrypted tar. Instead it is written to a standalone ``continuity.json``
    sidecar in the bundle dir, encrypted via :class:`StateEncryptor` when state
    encryption is enabled (honest plaintext when disabled). It is NEVER written
    into the plaintext manifest (that would re-leak the entity's inner life).
    """
    if backup.manifest_path is None:
        return False
    bundle_dir = backup.manifest_path.parent
    if not bundle_dir.is_dir():
        return False
    try:
        _write_sensitive_sidecar(
            bundle_dir / "continuity.json",
            json.dumps({"continuity_note": note}, indent=2),
        )
        return True
    except Exception:
        log.warning("update_manifest_continuity_note failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

# Entity state subtrees removed on decommission, relative to state_root.
_STATE_SUBTREES = tuple(
    [
        *legacy_aliases.name_forms("eidolon"),
        *legacy_aliases.name_forms("lingua"),
        *(Path(form) / "adapters" for form in legacy_aliases.name_forms("hypnos")),
        *legacy_aliases.name_forms("phantasia"),
        "forks",
        *legacy_aliases.name_forms("perception"),
        "individuation",
    ]
)

# Files under state/cycle that belong to the entity run (not the dir itself,
# which may hold operator config we leave alone — but these are entity files).
_CYCLE_FILES = ("runtime.json",)

# Other entity files, relative to state_root, that must be removed.
_STATE_FILES = (Path("preservation") / "divergence_edge.json",)


def delete_entity_state(
    *,
    state_root: Path,
    qdrant_cfg: dict[str, Any] | None,
    bus_client: Any = None,
    dry_run: bool = False,
    fork_root: Path | None = None,
    data_root: Path | None = None,
) -> DeleteResult:
    """Remove the entity's on-disk state, Qdrant collections, and Redis streams.

    Only ever operates under ``state_root``. With ``dry_run=True`` nothing is
    removed; the result reports what *would* be removed. Each step is guarded so
    a failure on one target does not abort the others.

    ``bus_client`` is a connected, authenticated Redis client for the stream
    step; it is not used for on-disk or Qdrant cleanup.
    """
    state_root = resolve(state_root)
    fork_root = resolve(fork_root) if fork_root is not None else state_root / "forks"
    data_root = resolve(data_root) if data_root is not None else state_root.parent / "data"
    result = DeleteResult(dry_run=dry_run)

    # --- Identity ---------------------------------------------------------
    entity_id: str | None = None
    try:
        identity = load_identity(state_root / "identity" / "entity.json")
        if identity is not None:
            entity_id = identity.entity_id
    except IdentityError as exc:
        result.errors.append(f"load identity for deletion: {exc}")
        entity_id = "unknown-entity"

    # Fold in Qdrant authentication and enumerate every on-disk location.
    qdrant_cfg = with_qdrant_api_key(qdrant_cfg)
    locations = entity_locations(
        qdrant_cfg,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        entity_id=entity_id,
    )

    # --- On-disk locations ------------------------------------------------
    protected = {
        Path("/").resolve(),
        Path.home().resolve(),
        state_root.resolve(),
        data_root.resolve(),
        data_root.parent.resolve(),
        fork_root.resolve(),
    }
    # Resolve every location before anything is removed: one location can sit
    # inside another (the language outcomes live in the language directory),
    # and an inner location removed with its parent still counts as deleted.
    present = {loc.key: loc.existing() for loc in locations}
    for loc in locations:
        if loc.decision not in (DELETE, BACKUP_DELETE):
            if loc.decision == RETAIN and present[loc.key]:
                result.retained_locations.append(loc.key)
            continue

        for path in present[loc.key]:
            if not dry_run and not path.exists() and not path.is_symlink():
                # Already removed together with an enclosing location.
                if loc.key not in result.deleted_locations:
                    result.deleted_locations.append(loc.key)
                continue
            if path.resolve() in protected:
                result.errors.append(f"refused to delete {path}: protected root")
                continue
            if dry_run:
                result.would_remove_paths.append(str(path))
                if loc.key not in result.deleted_locations:
                    result.deleted_locations.append(loc.key)
                continue
            try:
                if path.is_symlink():
                    path.unlink()
                    result.removed_paths.append(str(path))
                elif loc.contents_only and path.is_dir():
                    for child in path.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        result.removed_paths.append(str(child))
                elif path.is_dir():
                    shutil.rmtree(path)
                    result.removed_paths.append(str(path))
                else:
                    path.unlink()
                    result.removed_paths.append(str(path))
                if loc.key not in result.deleted_locations:
                    result.deleted_locations.append(loc.key)
            except Exception as exc:
                result.errors.append(f"remove {path}: {type(exc).__name__}: {exc}")

    # --- Qdrant collections (only when this deployment uses Qdrant) ---------
    if qdrant_in_use(qdrant_cfg):
        collections = _episodic_memory_collection_names(qdrant_cfg)
        prefix = _episodic_memory_prefix(qdrant_cfg)
        stamp_coll = EPISODIC_MEMORY_STAMP_COLLECTION
        stamp_key_str = stamp_key(prefix)
        stamp_pid = stamp_point_id(stamp_key_str)
        strength_key_str = strength_key(prefix)
        strength_pid = stamp_point_id(strength_key_str)
        if dry_run:
            result.dropped_collections = list(collections)  # would-drop
            result.dropped_collections.append(f"{stamp_coll}:{stamp_key_str}")
            result.dropped_collections.append(f"{stamp_coll}:{strength_key_str}")
        else:
            client = _qdrant_client(qdrant_cfg)
            if client is not None:
                try:
                    existing: set[str] = set()
                    probe_ok = False
                    try:
                        existing = {
                            c.name for c in client.get_collections().collections
                        }
                        probe_ok = True
                    except Exception as probe_exc:
                        # get_collections() failed: we do NOT know which collections
                        # exist.  Proceeding as if all were confirmed present would
                        # silently delete (or attempt to delete) collections we cannot
                        # verify exist, and would hide the probe failure.  Record the
                        # error and skip deletion rather than assuming.
                        result.errors.append(
                            f"qdrant get_collections probe failed "
                            f"({type(probe_exc).__name__}: {probe_exc}); "
                            f"collections not deleted (set unconfirmed)"
                        )
                        log.warning(
                            "delete_entity_state: qdrant get_collections failed; "
                            "skipping collection deletion (cannot confirm which exist)",
                            exc_info=True,
                        )
                    if probe_ok:
                        collection_drop_failed = False
                        for coll in collections:
                            if coll not in existing:
                                continue
                            try:
                                client.delete_collection(collection_name=coll)
                                result.dropped_collections.append(coll)
                            except Exception as exc:
                                collection_drop_failed = True
                                result.errors.append(f"drop collection {coll}: {exc}")
                        if stamp_coll in existing:
                            try:
                                from qdrant_client import models

                                if collection_drop_failed:
                                    points = [stamp_pid]
                                    result.errors.append(
                                        "mnemos strength meta kept because a collection drop failed"
                                    )
                                else:
                                    points = [stamp_pid, strength_pid]
                                client.delete(
                                    collection_name=stamp_coll,
                                    points_selector=models.PointIdsList(points=points),
                                )
                                result.dropped_collections.append(
                                    f"{stamp_coll}:{stamp_key_str}"
                                )
                                if not collection_drop_failed:
                                    result.dropped_collections.append(
                                        f"{stamp_coll}:{strength_key_str}"
                                    )
                            except Exception as exc:
                                result.errors.append(f"delete stamp {stamp_key_str}: {exc}")
                finally:
                    try:
                        client.close()
                    except Exception:
                        # Best-effort: deletion attempts above already recorded
                        # their own outcomes; a failure to close the connection
                        # doesn't change what was (or wasn't) dropped.
                        log.debug(
                            "delete_entity_state: qdrant client close failed",
                            exc_info=True,
                        )
            else:
                result.errors.append("qdrant unreachable; collections not dropped")

    # --- Redis entity streams (best-effort) --------------------------------
    streams = _entity_redis_streams(None)
    clear = clear_entity_streams(bus_client, streams, dry_run=dry_run)
    result.cleared_redis_streams = clear.would_clear if dry_run else clear.cleared
    result.skipped_non_streams = clear.skipped_non_streams
    result.redis_failed = clear.failed
    result.aof_rewrite = clear.aof_rewrite
    result.rdb_snapshot = clear.rdb_snapshot

    return result


DECOMMISSION_AUDIT_RELPATH = Path("audit") / "decommission.jsonl"


def write_decommission_audit(state_root: Path, record: dict[str, Any]) -> Path:
    """Append one decommission record under ``state_root``; names and counts only, never content."""
    audit_dir = state_root / DECOMMISSION_AUDIT_RELPATH.parent
    audit_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(audit_dir, 0o700)
    except Exception:
        log.warning("decommission audit: could not restrict the audit directory to the owner", exc_info=True)

    path = audit_dir / DECOMMISSION_AUDIT_RELPATH.name
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True))
        fh.write("\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        log.warning("decommission audit: could not restrict the audit file to the owner", exc_info=True)

    return path


def _entity_redis_streams(redis_cfg: dict[str, Any] | None) -> list[str]:
    """Return the exact Redis stream keys that carry entity traffic.

    Decommissioning deletes the entity's bus streams by exact name, checking
    the key type with ``TYPE`` before calling ``UNLINK``. No ``SCAN`` or
    ``KEYS`` is used.

    The list includes:

    * every stream in ``kaine.bus.streams.KNOWN_STREAMS``;
    * the module stream produced by ``module_stream("positive_control")``
      from ``kaine.bus.schema`` (imported inside this function next to
      ``KNOWN_STREAMS`` to avoid import cycles);
    * ``cycle.control``;
    * for every stream name ``<head>.<rest>`` returned above, every renamed
      form of ``<head>`` using both ``kaine.legacy_names.MODULES`` and
      ``kaine.legacy_names.DEVELOPMENTAL``.  A form is the head itself, the
      ``new_key`` of the dict entry when the head is an old name, and every
      old name whose ``new_key`` equals the head.  This ensures that streams
      written before or after a module rename are both cleared.
    """
    from kaine import legacy_names
    from kaine.bus.schema import module_stream
    from kaine.bus.streams import KNOWN_STREAMS

    names: set[str] = set(KNOWN_STREAMS)
    names.add(module_stream("positive_control"))

    names.add("cycle.control")

    rename_maps = (legacy_names.MODULES, legacy_names.DEVELOPMENTAL)

    def _head_forms(head: str) -> set[str]:
        forms: set[str] = {head}
        for mapping in rename_maps:
            aliases: dict[str, set[str]] = {key: set() for key in mapping}
            for old_key, entry in mapping.items():
                new_key = entry.get("new_key")
                if not new_key:
                    continue
                aliases.setdefault(new_key, set())
                aliases[old_key].add(new_key)
                aliases[new_key].add(old_key)

            for key, alts in aliases.items():
                if head == key:
                    forms.update(alts)
                prefix = f"{key}_"
                if head.startswith(prefix):
                    suffix = head[len(prefix):]
                    for alt in alts:
                        forms.add(f"{alt}_{suffix}")
        return forms

    expanded: set[str] = set()
    for name in names:
        if "." in name:
            head, rest = name.split(".", 1)
            for form in _head_forms(head):
                expanded.add(f"{form}.{rest}")
        else:
            expanded.add(name)

    return sorted(expanded)


@dataclass
class StreamClearResult:
    """Outcome of :func:`clear_entity_streams`."""

    cleared: list[str] = field(default_factory=list)
    would_clear: list[str] = field(default_factory=list)
    skipped_non_streams: list[str] = field(default_factory=list)
    failed: str | None = None
    aof_rewrite: str | None = None
    rdb_snapshot: str | None = None


def clear_entity_streams(client: Any, names: list[str], *, dry_run: bool) -> StreamClearResult:
    """Clear the named Redis streams safely.

    ``client`` must be an authenticated Redis client (for example from
    ``kaine.bus.config.load_bus_config``). Each key is checked with ``TYPE``
    before deletion; keys that are not streams are reported but never deleted.
    After a real deletion, an AOF rewrite is requested when append-only mode
    is enabled and a fresh RDB snapshot is requested when snapshotting is enabled.
    """
    result = StreamClearResult()
    if client is None:
        result.failed = "no bus connection; streams not checked"
        return result

    try:
        client.ping()
    except Exception as exc:
        result.failed = (
            f"cannot reach or authenticate to the bus ({type(exc).__name__}); nothing was deleted"
        )
        return result

    for name in names:
        try:
            raw_type = client.type(name)
            key_type = raw_type.decode() if isinstance(raw_type, bytes) else str(raw_type)
        except Exception as exc:
            result.failed = f"bus error on {name} ({type(exc).__name__})"
            return result

        if key_type == "none":
            continue

        if key_type != "stream":
            result.skipped_non_streams.append(f"{name} ({key_type})")
            continue

        if dry_run:
            result.would_clear.append(name)
        else:
            try:
                client.unlink(name)
            except Exception as exc:
                result.failed = f"bus error on {name} ({type(exc).__name__})"
                return result
            result.cleared.append(name)

    if not dry_run and result.cleared:
        # AOF rewrite
        try:
            raw_cfg = client.config_get("appendonly")
            cfg = (
                {
                    k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in raw_cfg.items()
                }
                if isinstance(raw_cfg, dict)
                else {}
            )
            appendonly = str(cfg.get("appendonly", "")).lower()
        except Exception as exc:
            result.aof_rewrite = (
                f"unknown ({type(exc).__name__}): rewrite the append-only file manually"
            )
        else:
            if appendonly == "yes":
                try:
                    client.bgrewriteaof()
                except Exception as exc:
                    try:
                        from redis.exceptions import ResponseError
                    except Exception:
                        ResponseError = None  # type: ignore[assignment,misc]
                    if (
                        ResponseError is not None
                        and isinstance(exc, ResponseError)
                        and "already in progress" in str(exc)
                    ):
                        result.aof_rewrite = "already in progress"
                    else:
                        result.aof_rewrite = f"failed ({type(exc).__name__})"
                else:
                    result.aof_rewrite = "started"
            else:
                result.aof_rewrite = "not needed (append-only file off)"

        # RDB snapshot
        try:
            raw_cfg = client.config_get("save")
            cfg = (
                {
                    k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in raw_cfg.items()
                }
                if isinstance(raw_cfg, dict)
                else {}
            )
            save_val = cfg.get("save", "")
        except Exception as exc:
            result.rdb_snapshot = (
                f"unknown ({type(exc).__name__}): take a fresh snapshot manually"
            )
        else:
            if isinstance(save_val, str) and save_val.strip():
                try:
                    client.bgsave()
                except Exception as exc:
                    try:
                        from redis.exceptions import ResponseError
                    except Exception:
                        ResponseError = None  # type: ignore[assignment,misc]
                    if (
                        ResponseError is not None
                        and isinstance(exc, ResponseError)
                        and "already in progress" in str(exc)
                    ):
                        result.rdb_snapshot = "already in progress"
                    else:
                        result.rdb_snapshot = f"failed ({type(exc).__name__})"
                else:
                    result.rdb_snapshot = "started"
            else:
                result.rdb_snapshot = "not needed (snapshots off)"

    return result


# ---------------------------------------------------------------------------
# CLI entrypoint convenience
#
# The canonical CLI lives in kaine.lifecycle.__main__ (run via
# ``python -m kaine.lifecycle``). For operators who reach for
# ``python -m kaine.lifecycle.decommission`` we delegate to that same
# entrypoint with runpy. Delegating dynamically (rather than importing the
# entrypoint) keeps the dependency one-directional — the entrypoint imports
# these destructive primitives, never the reverse — so this module does not
# form an import cycle with kaine.lifecycle.__main__.
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    import runpy
    import sys

    sys.argv[0] = "python -m kaine.lifecycle"
    runpy.run_module("kaine.lifecycle", run_name="__main__", alter_sys=True)
