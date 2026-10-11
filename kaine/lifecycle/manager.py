# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import dataclasses
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kaine.lifecycle.preservation import PreservationResult

from kaine.lifecycle._merge_base import AdapterMerger, FakeAdapterMerger
from kaine.lifecycle.identity import (
    EntityIdentity,
    check_sidecar_agrees,
    fork_identity,
    identity_of_snapshot,
    legacy_identity,
    read_identity_sidecar,
    write_identity_sidecar,
)
from kaine.lifecycle.snapshot import (
    ARTIFACTS_DIRNAME,
    ForkSnapshot,
    _chmod_quietly,
    artifacts_dir,
    copy_artifacts,
    list_snapshots,
    load_snapshot,
    save_snapshot,
    snapshot_dir,
)
from kaine.lifecycle.strategies import (
    MergeStrategy,
    UnionMergeStrategy,
    default_strategies,
)
from kaine.storage import resolve

log = logging.getLogger(__name__)


class UnmergedAdaptersError(RuntimeError):
    """Raised when ForkManager.merge() would produce a snapshot with unmerged
    adapter weights because only FakeAdapterMerger is available but both
    parent snapshots carry trained adapters.

    Pass ``allow_unmerged_adapters=True`` to bypass (with operator awareness),
    or install the PEFT extra (``pip install -e .[training]``) so
    ``adapter_merger = 'auto'`` (the default) — or an explicit
    ``adapter_merger = 'ties_dare'`` plus ``[lifecycle.adapter_merge]`` —
    performs a real weight merge instead.
    """


class WorldModelChoiceRequiredError(ValueError):
    """Both merge parents carry a world model and the caller did not name which continues."""


# `AdapterMerger` (Protocol) and `FakeAdapterMerger` live in the leaf module
# `kaine.lifecycle._merge_base` so this orchestrator and the PEFT-backed
# `kaine.lifecycle.adapter_merge` both depend on that common leaf instead of on
# each other (breaking the former manager <-> adapter_merge import cycle). They
# are re-exported above so `kaine.lifecycle.manager.AdapterMerger` /
# `.FakeAdapterMerger` stay the public import path.


@runtime_checkable
class _ModuleLike(Protocol):
    name: str

    def serialize(self) -> dict[str, Any]:
        ...

    def deserialize(self, state: dict[str, Any]) -> None:
        ...


@runtime_checkable
class _RegistryLike(Protocol):
    def all_modules(self) -> Iterable[_ModuleLike]:
        ...


class ForkManager:
    """Captures, restores, forks, and merges KAINE state snapshots.

    Snapshots live under `root` (default `state/forks/`) as
    `<id>/snapshot.json`. The manager never starts or stops any module
    — `restore` only calls `deserialize` on already-instantiated
    modules.

    The manager never deletes a snapshot. The root holds preserved beings
    and Spot escalation snapshots, and removing an entity's state is the
    CAL-gated decommission path only (`kaine.lifecycle.decommission`).
    Disk space is checked before boot by `python -m kaine.preboot`.
    """

    def __init__(
        self,
        root: Path,
        *,
        strategies: dict[str, MergeStrategy] | None = None,
        default_strategy: MergeStrategy | None = None,
        adapter_merger: AdapterMerger | None = None,
        identity_source: Callable[[], EntityIdentity | None] | None = None,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._strategies: dict[str, MergeStrategy] = dict(default_strategies())
        if strategies:
            self._strategies.update(strategies)
        self._default_strategy: MergeStrategy = default_strategy or UnionMergeStrategy()
        # Default: auto-detect the PEFT extra and select the real TIES/DARE
        # merger when it's importable, falling back to FakeAdapterMerger
        # otherwise — mirrors the DreamerV3/EMA and CfC real-by-default
        # fallback pattern. Callers that build their own merger via
        # `merger_from_name` from `[lifecycle]` config (or pass one directly)
        # override this.
        self._adapter_merger: AdapterMerger = adapter_merger or merger_from_name("auto")
        # Reads the running being's identity (entity-identity D11). None means
        # snapshots carry no identity, as for tools and tests.
        self._identity_source = identity_source

    @property
    def root(self) -> Path:
        return self._root

    def _read_identity(self) -> tuple[EntityIdentity | None, str | None]:
        """Return the running entity identity, or None plus a reason string.

        Never raises. If the configured source is absent or raises, we capture
        the reason so snapshots/bundles can record that identity was unreadable
        without failing a welfare-protective preservation.
        """
        if self._identity_source is None:
            return (None, None)
        try:
            identity = self._identity_source()
        except Exception as exc:
            log.error("entity identity unreadable; continuing without it: %s", exc)
            return (None, f"{type(exc).__name__}: {exc}")
        return (identity, None)

    def _write_sidecar(self, snapshot_id: str, identity: EntityIdentity) -> None:
        """Write the plaintext identity sidecar; a snapshot that cannot carry one
        is kept and its metadata still carries the identity."""
        try:
            write_identity_sidecar(snapshot_dir(self._root, snapshot_id), identity)
        except Exception:
            log.error(
                "identity sidecar could not be written for snapshot %s; "
                "snapshot is kept and its metadata still carries the identity",
                snapshot_id,
                exc_info=True,
            )

    def snapshot(
        self,
        registry: _RegistryLike,
        *,
        label: str = "",
        adapters: list[str] | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ForkSnapshot:
        identity, identity_unreadable = self._read_identity()

        modules: dict[str, dict[str, Any]] = {}
        for module in registry.all_modules():
            try:
                modules[module.name] = copy.deepcopy(module.serialize())
            except Exception as exc:
                log.warning("module %s serialize failed: %s", module.name, exc)
                modules[module.name] = {"_serialize_error": str(exc)}
        snap_meta = dict(metadata or {})
        if identity is not None:
            snap_meta["identity"] = identity.to_dict()
        if identity_unreadable is not None:
            snap_meta["identity_unreadable"] = identity_unreadable
        snap = ForkSnapshot(
            parent_id=parent_id,
            label=label,
            timestamp=time.time(),
            modules=modules,
            adapters=list(adapters or []),
            metadata=snap_meta,
        )
        records: dict[str, Any] = {}
        for module in registry.all_modules():
            hook = getattr(module, "export_snapshot_artifacts", None)
            if not callable(hook):
                continue
            dest = artifacts_dir(self._root, snap.id, module.name)
            try:
                dest.mkdir(mode=0o700, parents=True, exist_ok=True)
                _chmod_quietly(dest, 0o700)
                _chmod_quietly(snapshot_dir(self._root, snap.id), 0o700)
                record = hook(dest)
                if not isinstance(record, dict):
                    record = {"captured": False, "reason": "hook returned no record"}
                records[module.name] = record
                try:
                    if dest.exists() and not any(dest.iterdir()):
                        os.rmdir(dest)
                except OSError:
                    log.debug("could not remove empty artifact dir %s", dest, exc_info=True)
            except Exception:
                shutil.rmtree(snapshot_dir(self._root, snap.id), ignore_errors=True)
                raise
        if records:
            snap = dataclasses.replace(
                snap, metadata={**snap.metadata, "artifacts": records}
            )
        try:
            save_snapshot(self._root, snap)
        except Exception:
            shutil.rmtree(snapshot_dir(self._root, snap.id), ignore_errors=True)
            raise
        if identity is not None:
            self._write_sidecar(snap.id, identity)
        return snap

    def restore(self, snapshot_id: str, registry: _RegistryLike) -> ForkSnapshot:
        snap = load_snapshot(self._root, snapshot_id)
        for module in registry.all_modules():
            state = snap.modules.get(module.name)
            if state is None:
                continue
            try:
                module.deserialize(copy.deepcopy(state))
            except Exception as exc:
                log.warning("module %s deserialize failed: %s", module.name, exc)
        for module in registry.all_modules():
            hook = getattr(module, "import_snapshot_artifacts", None)
            if callable(hook):
                hook(artifacts_dir(self._root, snapshot_id, module.name))
        return snap

    def fork(
        self,
        parent_id: str,
        *,
        label: str = "",
        shed: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ForkSnapshot:
        parent = load_snapshot(self._root, parent_id)
        parent_identity = identity_of_snapshot(parent)
        if parent_identity is not None:
            check_sidecar_agrees(
                read_identity_sidecar(snapshot_dir(self._root, parent.id)),
                parent_identity,
            )

        if parent_identity is not None:
            child_identity = fork_identity(parent_identity)
        else:
            child_identity = fork_identity(legacy_identity(f"snapshot:{parent.id}"))

        shed_set = set(shed)
        modules = {
            name: copy.deepcopy(state)
            for name, state in parent.modules.items()
            if name not in shed_set
        }
        child_meta = {
            **parent.metadata,
            **(metadata or {}),
            "shed": sorted(shed_set),
        }
        child_meta["identity"] = child_identity.to_dict()
        if parent_identity is None:
            child_meta["forked_from_unidentified"] = parent.id
        child = ForkSnapshot(
            parent_id=parent.id,
            label=label,
            timestamp=time.time(),
            modules=modules,
            adapters=list(parent.adapters),
            metadata=child_meta,
        )
        parent_artifacts_root = snapshot_dir(self._root, parent.id) / ARTIFACTS_DIRNAME
        copied_names: list[str] = []
        if parent_artifacts_root.is_dir():
            for src in sorted(parent_artifacts_root.iterdir()):
                if src.is_symlink():
                    log.warning("skipping symlinked artifact directory: %s", src)
                    continue
                if not src.is_dir():
                    continue
                name = src.name
                if name in shed_set:
                    continue
                dst = artifacts_dir(self._root, child.id, name)
                try:
                    copy_artifacts(src, dst)
                    copied_names.append(name)
                except Exception:
                    shutil.rmtree(snapshot_dir(self._root, child.id), ignore_errors=True)
                    raise
        if copied_names:
            child = dataclasses.replace(
                child,
                metadata={**child.metadata, "artifacts_from_parent": sorted(copied_names)},
            )
        save_snapshot(self._root, child)
        self._write_sidecar(child.id, child_identity)
        return child

    def merge(
        self,
        snapshot_a_id: str,
        snapshot_b_id: str,
        *,
        label: str = "",
        strategies: dict[str, MergeStrategy] | None = None,
        metadata: dict[str, Any] | None = None,
        allow_unmerged_adapters: bool = False,
        world_model_from: str | None = None,
    ) -> ForkSnapshot:
        if world_model_from is not None and world_model_from not in ("a", "b"):
            raise ValueError("world_model_from must be 'a', 'b', or None")
        snap_a = load_snapshot(self._root, snapshot_a_id)
        snap_b = load_snapshot(self._root, snapshot_b_id)
        a_identity = identity_of_snapshot(snap_a)
        b_identity = identity_of_snapshot(snap_b)
        if a_identity is not None:
            check_sidecar_agrees(
                read_identity_sidecar(snapshot_dir(self._root, snap_a.id)),
                a_identity,
            )
        if b_identity is not None:
            check_sidecar_agrees(
                read_identity_sidecar(snapshot_dir(self._root, snap_b.id)),
                b_identity,
            )

        a_ph_dir = artifacts_dir(self._root, snap_a.id, "phantasia")
        b_ph_dir = artifacts_dir(self._root, snap_b.id, "phantasia")
        a_has = a_ph_dir.is_dir() and not a_ph_dir.is_symlink()
        b_has = b_ph_dir.is_dir() and not b_ph_dir.is_symlink()
        if a_has and b_has and world_model_from is None:
            raise WorldModelChoiceRequiredError(
                "both parents carry a Phantasia world model; merge cannot average "
                "two world models — pass world_model_from='a' or 'b' to choose "
                "which parent's world model continues"
            )
        all_strategies = dict(self._strategies)
        if strategies:
            all_strategies.update(strategies)

        merged_modules: dict[str, dict[str, Any]] = {}
        all_names = set(snap_a.modules) | set(snap_b.modules)
        for name in sorted(all_names):
            strat = all_strategies.get(name, self._default_strategy)
            state_a = snap_a.modules.get(name)
            state_b = snap_b.modules.get(name)
            try:
                merged_modules[name] = strat.merge(state_a, state_b)
            except Exception as exc:
                log.warning("merge strategy for %s failed: %s", name, exc)
                merged_modules[name] = state_a if state_a is not None else (state_b or {})

        merged_adapters, adapter_meta = self._adapter_merger.merge(
            list(snap_a.adapters), list(snap_b.adapters)
        )

        # Refuse to produce a silently-unmerged snapshot when both parents have
        # trained adapters and only the no-op FakeAdapterMerger is configured,
        # or when a real merge was attempted but rejected/failed. The resulting
        # snapshot would claim to be "merged" while its adapters were never
        # weight-combined — a pretend process. Operators who knowingly accept
        # this (e.g. they will merge adapters manually) must pass
        # allow_unmerged_adapters=True explicitly.
        if (
            adapter_meta.get("adapter_merge_skipped")
            and snap_a.adapters
            and snap_b.adapters
            and not allow_unmerged_adapters
        ):
            raise UnmergedAdaptersError(
                f"Both parents have trained adapters "
                f"({len(snap_a.adapters)} in {snap_a.id!r}, "
                f"{len(snap_b.adapters)} in {snap_b.id!r}) but no real "
                f"adapter merger is available (reason: "
                f"{adapter_meta['adapter_merge_skipped']!r}). "
                f"The merged snapshot would contain unmerged adapter weights. "
                f"To enable a real TIES/DARE merge: install the PEFT extra — "
                f"`pip install -e .[training]` (package extra `kaine[training]`) "
                f"— then set [lifecycle.adapter_merge].base_model_path to local "
                f"HuggingFace-format base model weights; adapter_merger = 'auto' "
                f"(the default) will then pick the real merger automatically, or "
                f"set adapter_merger = 'ties_dare' explicitly. To bypass without "
                f"merging weights: pass allow_unmerged_adapters=True."
            )

        # A merge that ran but was rejected by the merged-adapter checks, or
        # whose backend failed, never yields a snapshot unless the operator
        # explicitly keeps the parents' adapters uncombined.
        refusal = adapter_meta.get("adapter_merge_rejected") or adapter_meta.get(
            "adapter_merge_failed"
        )
        if refusal and not allow_unmerged_adapters:
            raise UnmergedAdaptersError(
                f"The adapter merge of {snap_a.id!r} and {snap_b.id!r} was "
                f"rejected or failed (reason: {refusal!r}). The merged adapter "
                f"was not kept and no merged snapshot was written. Pass "
                f"allow_unmerged_adapters=True to keep the parents' adapters "
                f"uncombined instead."
            )

        combined_meta: dict[str, Any] = {
            "merged_from": [snap_a.id, snap_b.id],
            **adapter_meta,
            **(metadata or {}),
        }
        if a_identity is not None:
            combined_meta["identity"] = a_identity.to_dict()
            if b_identity is not None:
                combined_meta["merged_from_entity"] = b_identity.entity_id

        merged = ForkSnapshot(
            parent_id=f"{snap_a.id}+{snap_b.id}",
            label=label,
            timestamp=time.time(),
            modules=merged_modules,
            adapters=merged_adapters,
            metadata=combined_meta,
        )
        a_root = snapshot_dir(self._root, snap_a.id) / ARTIFACTS_DIRNAME
        b_root = snapshot_dir(self._root, snap_b.id) / ARTIFACTS_DIRNAME
        a_names = {p.name for p in a_root.iterdir() if p.is_dir() and not p.is_symlink()} if a_root.is_dir() else set()
        b_names = {p.name for p in b_root.iterdir() if p.is_dir() and not p.is_symlink()} if b_root.is_dir() else set()
        sources: dict[str, str] = {}
        for name in sorted(a_names | b_names):
            if name == "phantasia" and a_has and b_has:
                chosen = "a" if world_model_from == "a" else "b"
                src = a_ph_dir if chosen == "a" else b_ph_dir
            elif name in a_names:
                chosen = "a"
                src = a_root / name
            else:
                chosen = "b"
                src = b_root / name
            dst = artifacts_dir(self._root, merged.id, name)
            if src.is_symlink():
                log.warning("skipping symlinked artifact directory: %s", src)
                continue
            if not src.is_dir():
                continue
            try:
                copy_artifacts(src, dst)
                sources[name] = chosen
            except Exception:
                shutil.rmtree(snapshot_dir(self._root, merged.id), ignore_errors=True)
                raise
        if sources:
            merged = dataclasses.replace(
                merged,
                metadata={**merged.metadata, "artifact_sources": sources},
            )
        save_snapshot(self._root, merged)
        if a_identity is not None:
            self._write_sidecar(merged.id, a_identity)
        return merged

    async def preserve_live(
        self,
        registry: _RegistryLike,
        *,
        reason: str = "individuation",
        label: str = "",
        out_root: Path | str = "backups",
        entity_name: str = "kaine",
        require_encryption: bool = False,
    ) -> "PreservationResult":
        """Preserve the whole live individual: a real snapshot + an encrypted
        bundle, written from the LIVE registry (read-only; never deletes).

        Delegates to :func:`kaine.lifecycle.preservation.preserve_live`. The
        snapshot lands under this manager's root; the bundle under ``out_root``.
        Stamps the event with the run_id and a fresh preservation id. Fails
        loudly if any component cannot be captured. When ``require_encryption``
        is set, fails closed (writes nothing) unless state encryption is active.
        """
        from kaine.lifecycle.preservation import preserve_live as _preserve_live

        identity, identity_unreadable = self._read_identity()
        return await _preserve_live(
            registry,
            fork_root=self._root,
            out_root=resolve(out_root),
            entity_name=entity_name,
            reason=reason,
            label=label,
            require_encryption=require_encryption,
            identity=identity,
            identity_unreadable=identity_unreadable,
        )

    async def revive(self, bundle: Path | str, registry: _RegistryLike) -> ForkSnapshot:
        """Reconstruct the same individual from a preservation bundle into a
        freshly-built ``registry`` (rehydrate; does not spawn a process).

        Delegates to :func:`kaine.lifecycle.preservation.revive`. Fails loudly
        if any captured component would be dropped.
        """
        from kaine.lifecycle.preservation import revive as _revive

        return await _revive(Path(bundle), registry)

    def list_snapshots(self) -> list[str]:
        return list_snapshots(self._root)

    def load(self, snapshot_id: str) -> ForkSnapshot:
        return load_snapshot(self._root, snapshot_id)


def merger_from_name(
    name: str,
    *,
    config_section: dict[str, Any] | None = None,
    merge_checks: Callable[[], tuple[Any, Any]] | None = None,
) -> AdapterMerger:
    """Resolve `adapter_merger` config key to a concrete instance.

    `"fake"` always returns the no-op merger that concatenates parent
    adapter paths, even when PEFT is installed — an explicit dev/no-extra
    selection. `"ties_dare"` always returns the PEFT-backed TIES/DARE
    merger (its own `merge()` falls back to a no-op per-call if PEFT
    turns out to be unavailable at merge time). `"auto"` — the shipped
    default — detects PEFT availability at resolution time via
    `kaine.lifecycle.adapter_merge.check_peft_available` and picks the
    real merger when possible, the no-op merger otherwise: real by
    default, fake as an explicit fallback, mirroring the DreamerV3/EMA
    and CfC real-by-default patterns.

    The optional `config_section` is the nested `[lifecycle.adapter_merge]`
    table, parsed into a `TiesDareMergeConfig` (consulted for `"ties_dare"`
    and `"auto"`; ignored for `"fake"`).

    The optional `merge_checks` is a callable that returns a
    ``(capability_eval, abliteration_scorer)`` pair.  It is called only
    when a real ``TiesDareAdapterMerger`` is about to be constructed;
    it is never called for ``"fake"`` and never called for ``"auto"``
    when the availability check forces a ``FakeAdapterMerger`` fallback.
    When it is called, its return values are wired into the real merger
    together with a model loader derived from ``base_model_path``.
    """
    if name == "fake":
        return FakeAdapterMerger()
    if name in ("ties_dare", "auto"):
        from kaine.lifecycle.adapter_merge import (
            TiesDareAdapterMerger,
            TiesDareMergeConfig,
            check_peft_available,
            peft_model_loader,
        )

        if name == "auto":
            missing = check_peft_available()
            if missing:
                log.info(
                    "merger_from_name('auto'): %s — using FakeAdapterMerger "
                    "(no real weight merge) until the extra is installed",
                    missing,
                )
                return FakeAdapterMerger()

        section = config_section or {}
        weights = section.get("weights") or []
        cfg = TiesDareMergeConfig(
            output_dir=resolve(
                section.get("output_dir", "state/forks/merged_adapters")
            ),
            combination_type=str(section.get("combination_type", "dare_ties")),
            density=float(section.get("density", 0.5)),
            weights=[float(w) for w in weights] if weights else None,
            capability_loss_threshold=float(
                section.get("capability_loss_threshold", 0.05)
            ),
            base_model_path=(
                str(section["base_model_path"]).strip() or None
                if section.get("base_model_path") is not None
                else None
            ),
        )

        capability_eval: Any = None
        abliteration_scorer: Any = None
        if merge_checks is not None:
            capability_eval, abliteration_scorer = merge_checks()

        model_loader: Any = None
        if cfg.base_model_path:
            model_loader = peft_model_loader(cfg.base_model_path)

        return TiesDareAdapterMerger(
            cfg,
            capability_eval=capability_eval,
            abliteration_scorer=abliteration_scorer,
            model_loader=model_loader,
        )
    raise ValueError(
        f"unknown adapter_merger {name!r}: known values are 'fake', 'ties_dare', 'auto'"
    )
