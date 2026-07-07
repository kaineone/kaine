# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare-gated entity decommission: transferable backup + state deletion.

This module implements the two destructive primitives the decommission CLI
(:mod:`kaine.lifecycle.__main__`) orchestrates:

* :func:`capture_backup` — produce ``backups/entity_<name>_<utc>/``: the
  entity's transferable self (Eidolon self-model, Lingua intent log, Hypnos
  voice adapters, Phantasia world-model weight checkpoints, the latest fork
  snapshot, a best-effort Qdrant export of the
  mnemos/empatheia collections) plus a ``manifest.json`` recording the
  divergence assessment, the continuity note, the file inventory, and restore
  notes. The bundle is encrypted with the existing state encryptor when state
  encryption is enabled. This satisfies CAL 4.2(b) ("saving the Entity's
  complete Cognitive State in a format that allows it to be restarted
  elsewhere"). Backup is **blocking**: a failure must abort decommission.

* :func:`delete_entity_state` — remove the on-disk state subtrees, drop the
  mnemos/empatheia Qdrant collections, and clear entity Redis streams. It only
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.memory_kinds import MNEMOS_COLLECTION_KINDS

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


def _mnemos_collection_names(qdrant_cfg: dict[str, Any] | None) -> list[str]:
    cfg = qdrant_cfg or {}
    prefix = str((cfg.get("mnemos") or {}).get("collection_prefix", "mnemos_"))
    names = [f"{prefix}{kind}" for kind in MNEMOS_COLLECTION_KINDS]
    empatheia = str((cfg.get("empatheia") or {}).get("collection", "empatheia_agents"))
    if empatheia:
        names.append(empatheia)
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


_QDRANT_INSTRUCTIONS = """\
Qdrant export could not be completed automatically (the server was unreachable
or the qdrant-client call failed). The entity's vector memory therefore was NOT
exported into this backup. To preserve it manually, copy the Qdrant data volume
BEFORE deleting it:

    docker run --rm -v kaine-qdrant-data:/data -v "$(pwd)":/backup \\
        alpine tar czf /backup/kaine-qdrant-data.tar.gz -C /data .

Collections belonging to this entity:
{collections}

Restore by extracting that tarball back into a fresh kaine-qdrant-data volume on
the target host before booting the restored entity.
"""


def capture_backup(
    *,
    state_root: Path,
    fork_root: Path,
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
    state_root = Path(state_root)
    out_root = Path(out_root)
    inventory: list[str] = []
    errors: list[str] = []

    bundle_dir = out_root / f"entity_{_safe_name(entity_name)}_{_utc_stamp()}"
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

    # --- 1. Eidolon self-model ------------------------------------------
    self_model_src = state_root / "eidolon" / "self_model.json"
    if self_model_src.is_file():
        try:
            shutil.copy2(self_model_src, bundle_dir / "self_model.json")
            inventory.append("self_model.json")
        except Exception as exc:
            errors.append(f"copy self_model.json: {exc}")

    # --- 2. Lingua intent expression log --------------------------------
    intent_src = state_root / "lingua" / "intent_expression.jsonl"
    if intent_src.is_file():
        try:
            shutil.copy2(intent_src, bundle_dir / "intent_expression.jsonl")
            inventory.append("intent_expression.jsonl")
        except Exception as exc:
            errors.append(f"copy intent_expression.jsonl: {exc}")

    # --- 3. Hypnos voice adapters ---------------------------------------
    adapters_src = state_root / "hypnos" / "adapters"
    if adapters_src.is_dir():
        try:
            shutil.copytree(adapters_src, bundle_dir / "adapters", dirs_exist_ok=True)
            inventory.append("adapters/")
        except Exception as exc:
            errors.append(f"copy adapters/: {exc}")

    # --- 4. Phantasia world-model weight checkpoints ---------------------
    # Learned-from-experience RSSM weights (opt-in persist_weights). The whole
    # directory is copied so custom checkpoint filenames are covered. These
    # are transferable cognitive state per CAL 4.2(b) — learned weights, never
    # raw sense data (the trajectory buffer is never written to disk).
    phantasia_src = state_root / "phantasia"
    if phantasia_src.is_dir() and any(phantasia_src.iterdir()):
        try:
            shutil.copytree(
                phantasia_src, bundle_dir / "phantasia", dirs_exist_ok=True
            )
            inventory.append("phantasia/")
        except Exception as exc:
            errors.append(f"copy phantasia/: {exc}")

    # --- 5. Latest fork snapshot ----------------------------------------
    latest_snapshot_id: str | None = None
    try:
        from kaine.lifecycle.manager import ForkManager

        fm = ForkManager(Path(fork_root))
        snap_ids = fm.list_snapshots()
        if snap_ids:
            # list_snapshots is sorted by id name; pick the most recent by ts.
            best_ts = None
            for sid in snap_ids:
                try:
                    snap = fm.load(sid)
                    if best_ts is None or snap.timestamp >= best_ts:
                        best_ts, latest_snapshot_id = snap.timestamp, sid
                except Exception:
                    continue
            if latest_snapshot_id is not None:
                src = Path(fork_root) / latest_snapshot_id / "snapshot.json"
                if src.is_file():
                    shutil.copy2(src, bundle_dir / "snapshot.json")
                    inventory.append(f"snapshot.json (fork {latest_snapshot_id})")
    except Exception as exc:
        errors.append(f"copy latest fork snapshot: {exc}")

    # --- 6. Qdrant export (best-effort) ---------------------------------
    collections = _mnemos_collection_names(qdrant_cfg)
    qdrant_dir = bundle_dir / "qdrant"
    client = _qdrant_client(qdrant_cfg)
    qdrant_written: list[str] = []
    qdrant_errors: list[str] = []
    if client is not None:
        qdrant_written, qdrant_errors = _export_qdrant(client, collections, qdrant_dir)
        try:
            client.close()
        except Exception:
            pass
    if not qdrant_written:
        # Unreachable or every collection failed → write volume-copy instructions
        # rather than pretending success (never crash the backup).
        try:
            _atomic_write_text(
                bundle_dir / "QDRANT_BACKUP_INSTRUCTIONS.txt",
                _QDRANT_INSTRUCTIONS.format(
                    collections="\n".join(f"  - {c}" for c in collections)
                ),
            )
            inventory.append("QDRANT_BACKUP_INSTRUCTIONS.txt")
        except Exception as exc:
            errors.append(f"write qdrant instructions: {exc}")
    else:
        inventory.extend(qdrant_written)
    # Qdrant errors are informational (best-effort), not fatal.
    errors.extend(qdrant_errors)

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
        "restore_notes": (
            "This bundle preserves the entity's transferable cognitive state per "
            "CAL Article 4.2(b). To restore on another host: place self_model.json "
            "under state/eidolon/, intent_expression.jsonl under state/lingua/, "
            "adapters/ under state/hypnos/adapters/, phantasia/ (world-model "
            "weight checkpoints) under state/phantasia/, snapshot.json under "
            "state/forks/<id>/, and re-import the qdrant/*.jsonl exports (or restore "
            "the kaine-qdrant-data volume per QDRANT_BACKUP_INSTRUCTIONS.txt) before "
            "booting. Sensitive entity inner-life (continuity.json, assessment.json) "
            "is kept out of this manifest; with state encryption enabled it rides "
            "inside bundle.tar.enc — decrypt with the operator's KAINE_STATE_KEY first."
        ),
    }
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
                    except OSError:
                        pass
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
_STATE_SUBTREES = (
    "eidolon",
    "lingua",
    Path("hypnos") / "adapters",
    "phantasia",
    "forks",
    "perception",
)
# Files under state/cycle that belong to the entity run (not the dir itself,
# which may hold operator config we leave alone — but these are entity files).
_CYCLE_FILES = ("runtime.json",)


def delete_entity_state(
    *,
    state_root: Path,
    qdrant_cfg: dict[str, Any] | None,
    redis_cfg: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> DeleteResult:
    """Remove the entity's on-disk state, Qdrant collections, and Redis streams.

    Only ever operates under ``state_root``. With ``dry_run=True`` nothing is
    removed; the result reports what *would* be removed. Each step is guarded so
    a failure on one target does not abort the others.
    """
    state_root = Path(state_root)
    result = DeleteResult(dry_run=dry_run)

    # --- On-disk subtrees ----------------------------------------------
    targets: list[Path] = [state_root / sub for sub in _STATE_SUBTREES]
    targets += [state_root / "cycle" / f for f in _CYCLE_FILES]
    for target in targets:
        try:
            # Defensive: never operate outside state_root.
            target.resolve().relative_to(state_root.resolve())
        except Exception:
            result.errors.append(f"refused path outside state_root: {target}")
            continue
        if not target.exists():
            continue
        if dry_run:
            result.would_remove_paths.append(str(target))
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            result.removed_paths.append(str(target))
        except Exception as exc:
            result.errors.append(f"remove {target}: {type(exc).__name__}: {exc}")

    # --- Qdrant collections (best-effort) ------------------------------
    collections = _mnemos_collection_names(qdrant_cfg)
    if dry_run:
        result.dropped_collections = list(collections)  # would-drop
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
                    for coll in collections:
                        if coll not in existing:
                            continue
                        try:
                            client.delete_collection(collection_name=coll)
                            result.dropped_collections.append(coll)
                        except Exception as exc:
                            result.errors.append(f"drop collection {coll}: {exc}")
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        else:
            result.errors.append("qdrant unreachable; collections not dropped")

    # --- Redis entity streams (best-effort) ----------------------------
    streams = _entity_redis_streams(redis_cfg)
    if dry_run:
        result.cleared_redis_streams = list(streams)  # would-clear
    elif streams:
        cleared, redis_errs = _clear_redis_streams(redis_cfg, streams)
        result.cleared_redis_streams = cleared
        result.errors.extend(redis_errs)

    return result


def _entity_redis_streams(redis_cfg: dict[str, Any] | None) -> list[str]:
    """The bus stream keys that carry entity traffic.

    We clear by pattern at delete time rather than enumerate every type; this
    list seeds the dry-run report.
    """
    return ["kaine:*"]


def _clear_redis_streams(
    redis_cfg: dict[str, Any] | None, patterns: list[str]
) -> tuple[list[str], list[str]]:
    cleared: list[str] = []
    errors: list[str] = []
    cfg = redis_cfg or {}
    host = str(cfg.get("host", "127.0.0.1"))
    port = int(cfg.get("port", 6379))
    db = int(cfg.get("db", 0))
    password = cfg.get("password") or None
    try:
        import redis

        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        for pattern in patterns:
            try:
                for key in client.scan_iter(match=pattern, count=200):
                    try:
                        client.delete(key)
                        name = key.decode() if isinstance(key, bytes) else str(key)
                        cleared.append(name)
                    except Exception as exc:
                        errors.append(f"delete redis key: {exc}")
            except Exception as exc:
                errors.append(f"scan redis {pattern!r}: {exc}")
        try:
            client.close()
        except Exception:
            pass
    except Exception as exc:
        errors.append(f"redis unreachable; streams not cleared ({type(exc).__name__})")
    return cleared, errors


# ---------------------------------------------------------------------------
# CLI entrypoint convenience
#
# The canonical CLI lives in kaine.lifecycle.__main__ (run via
# ``python -m kaine.lifecycle``). For operators who reach for
# ``python -m kaine.lifecycle.decommission`` we re-export and dispatch to the
# same main().
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin shim
    from kaine.lifecycle.__main__ import main as _main

    return _main(argv)


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
