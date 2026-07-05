# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live-entity preservation + revive (the welfare safety-net core).

This is the capture/restore core of the ``entity-preservation-on-divergence``
change. It preserves the WHOLE individual from a *live* registry and revives it
into a fresh (already-built) registry as the same individual.

What "the whole individual" means here (design.md §2):

* **self-model** — Eidolon ``serialize()`` (identity + values + drift).
* **memories** — Mnemos full store (short-term buffer + persisted episodic/
  semantic/procedural points), captured via the async
  ``export_preservation_state`` (which FAILS LOUDLY on an unreachable store).
* **world model** — Phantasia learned weights, when a learning backend +
  ``persist_weights`` are configured (flushed to the checkpoint and copied into
  the bundle); recorded HONESTLY as not-captured for the fake/off case.
* **affect / drives** — Thymos and Soma ``serialize()``.
* **adapters** — Hypnos voice adapters (already on disk; copied by the bundle).

Honesty invariants (feedback_no_pretend_processes):

* A component that cannot be captured raises — :func:`preserve_live` NEVER writes
  a partial bundle that looks complete.
* A revive that would drop any captured component raises — :func:`revive` NEVER
  produces a lesser individual.

This module is READ-ONLY on the live entity: it only calls ``serialize()`` /
``export_preservation_state`` / a weight checkpoint flush. It never deletes
anything (decommission's destructive path is separate).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kaine.lifecycle.snapshot import ForkSnapshot, load_snapshot, save_snapshot
from kaine.experiment.run_context import _utc_iso, get_run_context

log = logging.getLogger(__name__)


class PreservationError(RuntimeError):
    """Raised when preservation cannot capture the whole individual.

    A partial bundle that silently omits part of the individual is worse than
    an honest failure — the operator/monitor must know the safety net did not
    fully fire."""


class ReviveError(RuntimeError):
    """Raised when a revive would drop a captured component (a lesser
    individual). Revive fails loudly rather than booting an incomplete self."""


@dataclass
class PreservationResult:
    """Outcome of :func:`preserve_live`."""

    ok: bool
    preservation_id: str
    snapshot_id: str
    reason: str
    label: str
    run_id: str | None
    world_model_captured: bool
    inventory: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    import os

    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


async def _capture_module_state(module: Any) -> dict[str, Any]:
    """Capture one module's full preservation state.

    Starts from the synchronous ``serialize()`` and, when the module exposes the
    async ``export_preservation_state`` hook (Mnemos), merges its richer capture
    in. Any failure propagates (fail-loud) — a module that cannot be captured
    aborts the whole preservation.
    """
    try:
        state = copy.deepcopy(module.serialize())
    except Exception as exc:
        raise PreservationError(
            f"module {getattr(module, 'name', module)!r} serialize() failed during "
            f"preservation: {type(exc).__name__}: {exc}"
        ) from exc
    exporter = getattr(module, "export_preservation_state", None)
    if callable(exporter):
        try:
            rich = await exporter()
        except Exception as exc:
            raise PreservationError(
                f"module {getattr(module, 'name', module)!r} preservation capture "
                f"failed: {type(exc).__name__}: {exc}"
            ) from exc
        state.update(rich)
    return state


async def preserve_live(
    registry: Any,
    *,
    fork_root: Path,
    out_root: Path,
    entity_name: str,
    reason: str,
    label: str = "",
    require_encryption: bool = False,
) -> PreservationResult:
    """Preserve the whole individual from a LIVE registry. Read-only; fail-loud.

    Steps:
      1. Capture every module's state (serialize + async preservation exports).
         Mnemos carries its full memory store; a failure here raises.
      2. Flush Phantasia learned weights to the checkpoint (when persistence is
         on) and record honestly whether the world model was captured.
      3. Save a real fork snapshot of the captured states (encrypted at rest).
      4. Write a self-contained, encrypted preservation bundle (snapshot copy +
         phantasia checkpoint + manifest stamped with run_id + preservation id).

    Never interrupts the running entity and never deletes anything.

    ``require_encryption`` (paper §3.7 — "Encryption ships disabled and fails
    closed when enabled without a key"): when True, refuse to write an
    UNENCRYPTED preservation. If the process-global :class:`StateEncryptor` is
    not enabled (disabled, or — impossibly, since the constructor resolves the
    key at startup — keyless), this raises :class:`PreservationError` BEFORE any
    snapshot or bundle is written, so no plaintext artifact ever lands on disk.
    The runtime safety-net monitors pass the operator's
    ``[preservation].require_encryption`` here, so an unsupervised research run
    cannot silently persist a diverging/distressed individual in the clear.
    """
    fork_root = Path(fork_root)
    out_root = Path(out_root)
    preservation_id = uuid.uuid4().hex[:16]
    ctx = get_run_context()
    run_id = ctx.run_id if ctx is not None else None

    # Fail CLOSED before touching disk: if encryption is required but the
    # process-global encryptor is not actively encrypting, write NOTHING (no
    # plaintext snapshot, no plaintext bundle). A loud refusal is safer than a
    # complete-looking plaintext capture of the whole individual.
    if require_encryption:
        from kaine.security.crypto import get_state_encryptor

        if not getattr(get_state_encryptor(), "enabled", False):
            raise PreservationError(
                "require_encryption is set but state-at-rest encryption is not "
                "active (disabled, or no key): refusing to write an unencrypted "
                "preservation — nothing was written. Enable "
                "[security.state_encryption] with a key, or set "
                "[preservation].require_encryption = false."
            )

    modules = list(registry.all_modules())

    # --- 1. Capture every module's state (fail-loud) --------------------
    module_states: dict[str, dict[str, Any]] = {}
    for module in modules:
        module_states[module.name] = await _capture_module_state(module)

    # --- 2. Flush Phantasia learned weights + honest capture record -----
    world_model_captured = False
    phantasia_checkpoint: Path | None = None
    for module in modules:
        flush = getattr(module, "export_preservation_weights", None)
        if callable(flush):
            # Flushing learned weights to a checkpoint is blocking disk I/O;
            # run it off the event loop. Raises if persistence on but save failed.
            record = await asyncio.to_thread(flush)
            module_states[module.name]["world_model_capture"] = record
            if record.get("captured"):
                world_model_captured = True
                ckpt = record.get("checkpoint_path")
                if ckpt:
                    phantasia_checkpoint = Path(ckpt)

    # --- 3. Save a real fork snapshot of the live registry --------------
    # Voice adapters: prefer a module-exposed accessor (Hypnos), else fall back
    # to whatever the captured state recorded. Adapter *files* live on disk under
    # state/hypnos/adapters and are copied by the decommission/transfer bundle;
    # the snapshot records their paths so revive knows the individual has them.
    adapters: list[str] = []
    for module in modules:
        accessor = getattr(module, "preservation_adapters", None)
        if callable(accessor):
            try:
                adapters = [str(p) for p in (accessor() or [])]
            except Exception as exc:
                raise PreservationError(
                    f"module {module.name!r} adapter capture failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        elif module_states[module.name].get("adapters"):
            adapters = list(module_states[module.name]["adapters"])

    snap = ForkSnapshot(
        parent_id=None,
        label=label or f"preservation:{reason}",
        timestamp=time.time(),
        modules=module_states,
        adapters=adapters,
        metadata={
            "kind": "preservation",
            "reason": reason,
            "preservation_id": preservation_id,
            "run_id": run_id,
            "world_model_captured": world_model_captured,
        },
    )
    # Snapshot json+encrypt+write is synchronous disk/crypto work; run it off the
    # event loop so a preservation (which fires during distress/divergence) does
    # not stall the cognitive cycle.
    await asyncio.to_thread(save_snapshot, fork_root, snap)

    # --- 4. Write the encrypted, self-contained bundle ------------------
    # The bundle is made structurally consistent with the decommission backup:
    # all entity-interior content (the snapshot — which holds the WHOLE
    # individual incl. memories — plus phantasia learned weights) is tarred and,
    # when state encryption is enabled, the tar is encrypted via StateEncryptor;
    # the plaintext originals are removed on success. Only the NON-sensitive
    # manifest stays loose. When encryption is DISABLED (the shipped default) the
    # tar is plaintext (bundle.tar) — the same disabled-default at-rest risk the
    # rest of the state tree carries; operators enable [security.state_encryption]
    # to encrypt at rest. S8: the operator-supplied label is sanitised before it
    # is written into the manifest.
    safe_label = _safe(label) if label else ""
    bundle_dir = out_root / f"preservation_{preservation_id}_{_safe(entity_name)}"

    def _write_bundle() -> tuple[list[str], bool, dict[str, Any]]:
        """Stage → tar → (optionally) encrypt → write bundle + manifest.

        All synchronous disk/crypto work; runs in a worker thread via
        ``asyncio.to_thread`` so a preservation does not stall the cognitive
        cycle. Returns ``(inventory, bundle_encrypted, manifest)``.
        """
        import shutil
        import tarfile

        inventory: list[str] = []
        out_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _chmod_quietly(out_root, 0o700)
        bundle_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        _chmod_quietly(bundle_dir, 0o700)

        # Stage entity-interior content in the bundle dir (then tar + optionally
        # encrypt it). The snapshot already contains the full individual; copy
        # the (snapshot-level encrypted) snapshot.json verbatim so the bundle is
        # self-contained.
        snap_src = fork_root / snap.id / "snapshot.json"
        shutil.copy2(snap_src, bundle_dir / "snapshot.json")
        _chmod_quietly(bundle_dir / "snapshot.json", 0o600)
        inventory.append(f"snapshot.json (preservation snapshot {snap.id})")

        # Phantasia learned-weight checkpoint (only when actually captured).
        if phantasia_checkpoint is not None and phantasia_checkpoint.is_file():
            (bundle_dir / "phantasia").mkdir(mode=0o700, exist_ok=True)
            _chmod_quietly(bundle_dir / "phantasia", 0o700)
            shutil.copy2(
                phantasia_checkpoint,
                bundle_dir / "phantasia" / phantasia_checkpoint.name,
            )
            _chmod_quietly(bundle_dir / "phantasia" / phantasia_checkpoint.name, 0o600)
            inventory.append(
                f"phantasia/{phantasia_checkpoint.name} (world-model weights)"
            )

        # Tar the staged content and (when enabled) encrypt the tar via the same
        # StateEncryptor path the decommission backup uses, then remove the
        # plaintext originals. The manifest is excluded (stays loose + readable).
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()
        bundle_encrypted = bool(getattr(encryptor, "enabled", False))
        tar_member_names = ["snapshot.json"]
        if (bundle_dir / "phantasia").is_dir():
            tar_member_names.append("phantasia")
        tar_bytes_path = bundle_dir / "_bundle.tar"
        with tarfile.open(tar_bytes_path, "w") as tar:
            for name in tar_member_names:
                tar.add(bundle_dir / name, arcname=name)
        raw = tar_bytes_path.read_bytes()
        tar_bytes_path.unlink()
        if bundle_encrypted:
            blob = encryptor.encrypt(raw)  # bytes in, base64 bytes out
            (bundle_dir / "bundle.tar.enc").write_text(blob.decode("ascii"))
            _chmod_quietly(bundle_dir / "bundle.tar.enc", 0o600)
            bundle_artifact = "bundle.tar.enc (encrypted)"
        else:
            (bundle_dir / "bundle.tar").write_bytes(raw)
            _chmod_quietly(bundle_dir / "bundle.tar", 0o600)
            bundle_artifact = (
                "bundle.tar (PLAINTEXT — enable state encryption to protect at rest)"
            )
        # Remove the now-tarred plaintext originals.
        for name in tar_member_names:
            target = bundle_dir / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                try:
                    target.unlink()
                except OSError:
                    pass
        inventory.append(bundle_artifact)

        manifest = {
            "kind": "preservation",
            "preservation_id": preservation_id,
            "snapshot_id": snap.id,
            "entity_name": entity_name,
            "reason": reason,
            "label": safe_label,
            "run_id": run_id,
            "timestamp": _utc_iso(),
            "world_model_captured": world_model_captured,
            "modules": sorted(module_states.keys()),
            "inventory": inventory,
            "encrypted": bundle_encrypted,
            "restore_notes": (
                "Self-contained preservation bundle. Entity-interior content "
                "(snapshot.json — every module's full preservation state: "
                "self-model, memories, affect/drive, adapter paths — plus "
                "phantasia/ world-model weights when captured) is tarred into "
                "bundle.tar(.enc); when state encryption is enabled the tar is "
                "StateEncryptor-encrypted (bundle.tar.enc). Revive via "
                "ForkManager.revive(bundle_dir, registry)."
            ),
        }
        manifest_path = bundle_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        _chmod_quietly(manifest_path, 0o600)
        inventory.append("manifest.json")
        return inventory, bundle_encrypted, manifest

    inventory, bundle_encrypted, manifest = await asyncio.to_thread(_write_bundle)

    log.info(
        "preserve_live: preserved entity %r (preservation_id=%s, snapshot=%s, "
        "reason=%s, world_model_captured=%s, run_id=%s)",
        entity_name,
        preservation_id,
        snap.id,
        reason,
        world_model_captured,
        run_id,
    )

    return PreservationResult(
        ok=True,
        preservation_id=preservation_id,
        snapshot_id=snap.id,
        reason=reason,
        label=label,
        run_id=run_id,
        world_model_captured=world_model_captured,
        inventory=inventory,
        manifest=manifest,
    )


async def revive(bundle: Path, registry: Any) -> ForkSnapshot:
    """Reconstruct the same individual from a preservation bundle into ``registry``.

    ``registry`` must already have the modules built (revive rehydrates state; it
    does not spawn a process). Restores self-model + memories + world-model
    weights + affect/drive + adapters. Fails loudly if any captured component
    cannot be restored — never produces a lesser individual.
    """
    bundle = Path(bundle)
    # The bundle stores entity-interior content inside bundle.tar(.enc); a legacy
    # bundle stored snapshot.json + phantasia/ loose. Resolve the snapshot from
    # whichever layout is present (fail loud if neither carries a snapshot).
    members = _read_bundle_members(bundle)
    if "snapshot.json" not in members:
        raise ReviveError(
            f"preservation bundle has no snapshot.json (tar or loose): {bundle}"
        )

    snap = ForkSnapshot.from_dict(json.loads(members["snapshot.json"]))

    by_name = {m.name: m for m in registry.all_modules()}

    # Which components the bundle claims to carry — used to fail loud if a
    # captured module is missing from the target registry.
    captured_modules = set(snap.modules.keys())
    missing = captured_modules - set(by_name.keys())
    if missing:
        raise ReviveError(
            f"revive target registry is missing modules the bundle captured: "
            f"{sorted(missing)} — refusing to revive a lesser individual"
        )

    for name, state in snap.modules.items():
        module = by_name[name]
        # Mnemos (and any future async-restoring module) carries a richer
        # capture that must be restored through its async importer.
        importer = getattr(module, "import_preservation_state", None)
        if "memory_state" in state and callable(importer):
            try:
                await importer(state)
            except Exception as exc:
                raise ReviveError(
                    f"revive failed restoring {name!r} memories: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            continue

        # Phantasia learned weights: restore from the bundled checkpoint blob.
        wm_record = state.get("world_model_capture")
        if (
            wm_record
            and wm_record.get("captured")
            and hasattr(module, "import_preservation_weights")
        ):
            blob = _load_bundle_phantasia_weights(members, wm_record)
            if blob is None:
                raise ReviveError(
                    f"revive: bundle records captured world-model weights for "
                    f"{name!r} but the checkpoint is absent from the bundle — "
                    "refusing to revive a world-model-less lesser individual"
                )
            try:
                module.import_preservation_weights(blob)
            except Exception as exc:
                raise ReviveError(
                    f"revive failed restoring {name!r} world-model weights: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            # Still apply the (metadata-only) deserialize for consistency.
            try:
                module.deserialize(copy.deepcopy(state))
            except Exception:
                pass
            continue

        try:
            module.deserialize(copy.deepcopy(state))
        except Exception as exc:
            raise ReviveError(
                f"revive failed restoring module {name!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    log.info(
        "revive: restored individual from preservation bundle %s "
        "(snapshot=%s, modules=%d, world_model_captured=%s)",
        bundle,
        snap.id,
        len(snap.modules),
        snap.metadata.get("world_model_captured"),
    )
    return snap


def _read_bundle_members(bundle: Path) -> dict[str, Any]:
    """Return the bundle's entity-interior members from bundle.tar(.enc) or loose.

    Resolves both the current (tar+optionally-encrypted) layout and a legacy
    loose layout (snapshot.json + phantasia/ on disk). Returns a dict:

    * ``"snapshot.json"`` -> decoded snapshot JSON text (snapshot-level framing
      transparently decrypted via :meth:`StateEncryptor.maybe_decrypt`).
    * ``"phantasia/<name>"`` -> raw checkpoint bytes for each captured weight file.

    Fails loud (ReviveError) if an encrypted tar cannot be decrypted/opened.
    """
    import io
    import tarfile

    from kaine.security.crypto import get_state_encryptor

    encryptor = get_state_encryptor()
    members: dict[str, Any] = {}

    enc_tar = bundle / "bundle.tar.enc"
    plain_tar = bundle / "bundle.tar"
    raw_tar: bytes | None = None
    if enc_tar.is_file():
        try:
            raw_tar = encryptor.decrypt(enc_tar.read_text().encode("ascii"))
        except Exception as exc:
            raise ReviveError(
                f"revive: could not decrypt preservation bundle tar {enc_tar} "
                f"({type(exc).__name__}: {exc}) — wrong/absent KAINE_STATE_KEY?"
            ) from exc
    elif plain_tar.is_file():
        raw_tar = plain_tar.read_bytes()

    if raw_tar is not None:
        try:
            with tarfile.open(fileobj=io.BytesIO(raw_tar)) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    fh = tf.extractfile(member)
                    if fh is None:
                        continue
                    data = fh.read()
                    if member.name == "snapshot.json":
                        members["snapshot.json"] = encryptor.maybe_decrypt(
                            data
                        ).decode("utf-8")
                    elif member.name.startswith("phantasia/"):
                        members[member.name] = data
        except ReviveError:
            raise
        except Exception as exc:
            raise ReviveError(
                f"revive: could not open preservation bundle tar {bundle} "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        return members

    # Legacy loose layout.
    snap_path = bundle / "snapshot.json"
    if snap_path.is_file():
        members["snapshot.json"] = encryptor.maybe_decrypt(
            snap_path.read_bytes()
        ).decode("utf-8")
    phantasia_dir = bundle / "phantasia"
    if phantasia_dir.is_dir():
        for p in sorted(phantasia_dir.iterdir()):
            if p.is_file():
                members[f"phantasia/{p.name}"] = p.read_bytes()
    return members


def _load_bundle_phantasia_weights(
    members: dict[str, Any], wm_record: dict[str, Any]
) -> bytes | None:
    """Decode the captured world-model checkpoint from the bundle members.

    The checkpoint rode in the bundle under ``phantasia/<name>``; it is decoded
    through the same checkpoint codec that wrote it (transparent for plaintext).
    Returns the param-tree blob, or None when the bundle has no phantasia
    checkpoint.
    """
    import tempfile

    from kaine.modules.phantasia.checkpoint import load_checkpoint

    phantasia_members = {
        k: v for k, v in members.items() if k.startswith("phantasia/")
    }
    if not phantasia_members:
        return None
    recorded = wm_record.get("checkpoint_path")
    chosen_key: str | None = None
    if recorded:
        want = f"phantasia/{Path(recorded).name}"
        if want in phantasia_members:
            chosen_key = want
    if chosen_key is None:
        chosen_key = sorted(phantasia_members.keys())[0]
    blob_bytes = phantasia_members[chosen_key]
    # load_checkpoint reads from a path; materialise the member bytes to a temp
    # file (the codec transparently handles plaintext/encrypted checkpoints).
    with tempfile.NamedTemporaryFile(suffix=Path(chosen_key).suffix) as tmp:
        tmp.write(blob_bytes)
        tmp.flush()
        return load_checkpoint(Path(tmp.name))


def _safe(name: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "_" for c in (name or "entity"))
    return cleaned or "entity"
