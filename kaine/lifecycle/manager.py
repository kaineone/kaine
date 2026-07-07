# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kaine.lifecycle.preservation import PreservationResult

from kaine.lifecycle._merge_base import AdapterMerger, FakeAdapterMerger
from kaine.lifecycle.snapshot import (
    ForkSnapshot,
    list_snapshots,
    load_snapshot,
    save_snapshot,
)
from kaine.lifecycle.strategies import (
    MergeStrategy,
    UnionMergeStrategy,
    default_strategies,
)

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
    """

    def __init__(
        self,
        root: Path,
        *,
        strategies: dict[str, MergeStrategy] | None = None,
        default_strategy: MergeStrategy | None = None,
        adapter_merger: AdapterMerger | None = None,
        max_snapshots_retained: int = 64,
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
        self._max_retained = int(max_snapshots_retained)

    @property
    def root(self) -> Path:
        return self._root

    def snapshot(
        self,
        registry: _RegistryLike,
        *,
        label: str = "",
        adapters: list[str] | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ForkSnapshot:
        modules: dict[str, dict[str, Any]] = {}
        for module in registry.all_modules():
            try:
                modules[module.name] = copy.deepcopy(module.serialize())
            except Exception as exc:
                log.warning("module %s serialize failed: %s", module.name, exc)
                modules[module.name] = {"_serialize_error": str(exc)}
        snap = ForkSnapshot(
            parent_id=parent_id,
            label=label,
            timestamp=time.time(),
            modules=modules,
            adapters=list(adapters or []),
            metadata=dict(metadata or {}),
        )
        save_snapshot(self._root, snap)
        self._enforce_retention()
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
        shed_set = set(shed)
        modules = {
            name: copy.deepcopy(state)
            for name, state in parent.modules.items()
            if name not in shed_set
        }
        child = ForkSnapshot(
            parent_id=parent.id,
            label=label,
            timestamp=time.time(),
            modules=modules,
            adapters=list(parent.adapters),
            metadata={**parent.metadata, **(metadata or {}), "shed": sorted(shed_set)},
        )
        save_snapshot(self._root, child)
        self._enforce_retention()
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
    ) -> ForkSnapshot:
        snap_a = load_snapshot(self._root, snapshot_a_id)
        snap_b = load_snapshot(self._root, snapshot_b_id)
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
        # trained adapters and only the no-op FakeAdapterMerger is configured.
        # The resulting snapshot would claim to be "merged" while its adapters
        # were never weight-combined — a pretend process.  Operators who
        # knowingly accept this (e.g. they will merge adapters manually) must
        # pass allow_unmerged_adapters=True explicitly.
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

        combined_meta: dict[str, Any] = {
            "merged_from": [snap_a.id, snap_b.id],
            **adapter_meta,
            **(metadata or {}),
        }
        merged = ForkSnapshot(
            parent_id=f"{snap_a.id}+{snap_b.id}",
            label=label,
            timestamp=time.time(),
            modules=merged_modules,
            adapters=merged_adapters,
            metadata=combined_meta,
        )
        save_snapshot(self._root, merged)
        self._enforce_retention()
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

        return await _preserve_live(
            registry,
            fork_root=self._root,
            out_root=Path(out_root),
            entity_name=entity_name,
            reason=reason,
            label=label,
            require_encryption=require_encryption,
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

    def _enforce_retention(self) -> None:
        if self._max_retained <= 0:
            return
        ids = self.list_snapshots()
        if len(ids) <= self._max_retained:
            return
        # Order by the snapshot file's mtime rather than decrypting+parsing every
        # snapshot just to read its ``timestamp`` field — the file's mtime tracks
        # write order (oldest first), which is exactly the eviction order. An
        # unstattable file sorts as oldest (0.0) so it is evicted first.
        files: list[tuple[float, str]] = []
        for snap_id in ids:
            try:
                mtime = (self._root / snap_id / "snapshot.json").stat().st_mtime
            except OSError:
                mtime = 0.0
            files.append((mtime, snap_id))
        files.sort()
        excess = len(files) - self._max_retained
        for _, snap_id in files[:excess]:
            target_dir = self._root / snap_id
            try:
                for path in target_dir.iterdir():
                    path.unlink()
                target_dir.rmdir()
            except Exception:
                log.warning("failed to evict snapshot %s", snap_id, exc_info=True)


def merger_from_name(
    name: str, *, config_section: dict[str, Any] | None = None
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
    """
    if name == "fake":
        return FakeAdapterMerger()
    if name in ("ties_dare", "auto"):
        from kaine.lifecycle.adapter_merge import (
            TiesDareAdapterMerger,
            TiesDareMergeConfig,
            check_peft_available,
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
            output_dir=Path(
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
        return TiesDareAdapterMerger(cfg)
    raise ValueError(
        f"unknown adapter_merger {name!r}: known values are 'fake', 'ties_dare', 'auto'"
    )
