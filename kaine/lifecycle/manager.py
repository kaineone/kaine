# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Mapping,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from kaine.lifecycle.preservation import PreservationResult
    from kaine.security.custody.encryptor import EntityEncryptor
    from kaine.security.custody.keyring import KeyRing

from kaine import legacy_aliases
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
    find_artifacts_dir,
    list_snapshots,
    load_snapshot,
    reencrypt_artifacts,
    save_snapshot,
    snapshot_dir,
)
from kaine.lifecycle.strategies import (
    MODULE_WEIGHT_GROUPS,
    MODULE_WEIGHT_PARAMETERS,
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


class ModuleWeightsChoiceRequiredError(ValueError):
    """The parents' learned weights differ for some modules and the caller did not
    name, for each of them, which parent's weights continue."""

    def __init__(self, holders: Mapping[str, tuple[str, ...]]) -> None:
        # Module name -> the parents ("a", "b") whose group holds learned
        # parameters, not only the bindings they were trained against.
        self.holders: dict[str, tuple[str, ...]] = {
            name: tuple(holders[name]) for name in sorted(holders)
        }
        self.modules: tuple[str, ...] = tuple(self.holders)
        parts = []
        for name, held in self.holders.items():
            if len(held) == 2:
                parts.append(f"{name} (both parents hold learned weights)")
            elif len(held) == 1:
                parts.append(
                    f"{name} (only {held[0]} holds learned weights; the parents' "
                    "bindings differ, so choosing the other parent leaves "
                    f"{name} without learned weights)"
                )
            else:
                parts.append(f"{name} (neither parent holds learned weights; the bindings differ)")
        super().__init__(
            f"the parents' learned weights differ for {'; '.join(parts)}. Merge "
            "cannot combine two sets of learned weights — pass "
            "module_weights_from='a' or 'b', or a mapping naming 'a' or 'b' for "
            "each of these modules, to choose which parent's weights continue"
        )


class ModuleMergeStrategyError(RuntimeError):
    """The merge strategy for a module that carries learned weights failed.

    Merge refuses instead of taking either parent's state in its place.
    """

    def __init__(self, module: str, cause: BaseException) -> None:
        self.module = module
        # The exception's message can quote state values; only its type is
        # carried here (the dashboard returns this text), the log has the rest.
        super().__init__(
            f"the merge strategy for {module} failed "
            f"({type(cause).__name__}); {module} carries learned "
            "weights, so merge refuses rather than take either parent's "
            "state in its place, and no merged snapshot was written"
        )


def _normalise_weights_choice(
    value: str | Mapping[str, str] | None,
) -> str | dict[str, str] | None:
    """Validate ``module_weights_from``: None, 'a', 'b', or {module: 'a'|'b'}."""
    if value is None:
        return None
    if isinstance(value, str):
        if value not in ("a", "b"):
            raise ValueError("module_weights_from must be 'a', 'b', a mapping, or None")
        return value
    if not isinstance(value, Mapping):
        raise ValueError("module_weights_from must be 'a', 'b', a mapping, or None")
    out: dict[str, str] = {}
    for raw_name, parent in value.items():
        if not isinstance(raw_name, str):
            raise ValueError(f"module_weights_from names a non-string module: {raw_name!r}")
        name = legacy_aliases.map_module_key(raw_name)
        if name in out:
            raise ValueError(
                f"module_weights_from names {name!r} twice (under an old and a "
                "current module name); name each module once"
            )
        if name not in MODULE_WEIGHT_GROUPS:
            raise ValueError(
                f"module_weights_from names {raw_name!r}, which carries no "
                f"weight group (modules with one: {', '.join(sorted(MODULE_WEIGHT_GROUPS))})"
            )
        if parent not in ("a", "b"):
            raise ValueError(
                f"module_weights_from[{raw_name!r}] must be 'a' or 'b', got {parent!r}"
            )
        out[name] = parent
    return out


def _weight_group(state: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    """The group's keys present in ``state``, or None when it holds none of them."""
    if not isinstance(state, dict):
        return None
    group = {k: state[k] for k in keys if k in state}
    return group or None


def _without_group(state: Any, keys: tuple[str, ...]) -> Any:
    """A deep copy of ``state`` without the group's keys (None stays None)."""
    if not isinstance(state, dict):
        return copy.deepcopy(state)
    return {k: copy.deepcopy(v) for k, v in state.items() if k not in keys}


# ForkManager.snapshot records a module whose serialize() raised as this key.
_SERIALIZE_ERROR_KEY = "_serialize_error"


def _without_serialize_error(state: Any) -> Any:
    """``state`` without a parent's serialize-error marker: the merged state is
    built from what each parent did capture, and is not itself an error."""
    if isinstance(state, dict) and _SERIALIZE_ERROR_KEY in state:
        return {k: v for k, v in state.items() if k != _SERIALIZE_ERROR_KEY}
    return state


def _weight_source(
    name: str,
    group_a: dict[str, Any] | None,
    group_b: dict[str, Any] | None,
) -> tuple[str | None, str, tuple[str, ...]]:
    """(parent, reason, holders) for a module's weight group.

    ``parent`` is None when the groups differ and the caller must choose;
    ``holders`` names the parents whose group holds learned parameters.
    """
    params = MODULE_WEIGHT_PARAMETERS.get(name, ())

    def has_params(group: dict[str, Any] | None) -> bool:
        return group is not None and any(k in group for k in params)

    holders = tuple(p for p, g in (("a", group_a), ("b", group_b)) if has_params(g))
    if group_b is None:
        return "a", "one-sided", holders
    if group_a is None:
        return "b", "one-sided", holders
    if group_a == group_b:
        return "a", "equal", holders
    if len(holders) == 1:
        # One parent holds bindings only. Its group is the other's minus the
        # parameters when the bindings both hold agree; then the parameters
        # come from the parent that has them, with their own bindings.
        shared = (set(group_a) & set(group_b)) - set(params)
        if all(group_a[k] == group_b[k] for k in shared):
            return holders[0], "one-sided", holders
    return None, "chosen", holders


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
        """Protocol method."""


def _artifact_dirs_by_module(root: Path) -> dict[str, Path]:
    """Map each artifact directory under ``root`` to its module key; a directory already under the current name wins over an old-named one."""
    if not root.is_dir():
        return {}
    found: dict[str, Path] = {}
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.is_symlink():
            continue
        key = legacy_aliases.map_module_key(p.name)
        if key not in found or p.name == key:
            found[key] = p
    return found


def _self_model_state_name(modules: dict[str, Any]) -> str | None:
    """The name inside a snapshot's captured self-model state, or None."""
    try:
        name = json.loads(modules["self_model"]["model"]).get("name")
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None


class ForkManager:
    """Captures, restores, forks, and merges KAINE state snapshots.

    Snapshots live under `root` (default `state/forks/`) as
    `<id>/snapshot.json`. The manager never starts or stops any module
    — `restore` only calls `deserialize` on already-instantiated
    modules.

    The manager never deletes a snapshot. The root holds preserved entities
    and supervisor escalation snapshots, and removing an entity's state is the
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
        keyring: KeyRing | None = None,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._strategies: dict[str, MergeStrategy] = dict(default_strategies())
        if strategies:
            self._strategies.update(strategies)
        self._default_strategy: MergeStrategy = default_strategy or UnionMergeStrategy()
        self._adapter_merger: AdapterMerger = adapter_merger or merger_from_name("auto")
        self._identity_source = identity_source
        self._keyring = keyring

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

    def _encryptor_for(self, entity_id: str) -> EntityEncryptor | None:
        if self._keyring is None:
            return None
        return self._keyring.encryptor_for(entity_id)

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
        enc = self._encryptor_for(identity.entity_id) if identity is not None else None
        try:
            save_snapshot(self._root, snap, encryptor=enc)
        except Exception:
            shutil.rmtree(snapshot_dir(self._root, snap.id), ignore_errors=True)
            raise
        if identity is not None:
            self._write_sidecar(snap.id, identity)
        return snap

    def restore(self, snapshot_id: str, registry: _RegistryLike) -> ForkSnapshot:
        enc = None
        if self._keyring is not None:
            sidecar = read_identity_sidecar(snapshot_dir(self._root, snapshot_id))
            if sidecar is not None:
                enc = self._encryptor_for(sidecar.entity_id)
        snap = load_snapshot(self._root, snapshot_id, encryptor=enc)
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
                hook(find_artifacts_dir(self._root, snapshot_id, module.name))
        return snap

    def fork(
        self,
        parent_id: str,
        *,
        label: str = "",
        shed: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ForkSnapshot:
        parent_enc = None
        if self._keyring is not None:
            parent_sidecar = read_identity_sidecar(snapshot_dir(self._root, parent_id))
            if parent_sidecar is not None:
                parent_enc = self._encryptor_for(parent_sidecar.entity_id)
        parent = load_snapshot(self._root, parent_id, encryptor=parent_enc)
        parent_identity = identity_of_snapshot(parent)
        if parent_identity is not None:
            check_sidecar_agrees(
                read_identity_sidecar(snapshot_dir(self._root, parent.id)),
                parent_identity,
            )

        # An unnamed parent's name lives only in its self-model state; the fork must
        # not draw it.
        avoid = [n for n in (_self_model_state_name(parent.modules),) if n]
        if parent_identity is not None:
            child_identity = fork_identity(
                parent_identity, avoid_names=avoid, parent_known_name=(avoid[0] if avoid else None)
            )
        else:
            child_identity = fork_identity(
                legacy_identity(f"snapshot:{parent.id}"),
                avoid_names=avoid,
                parent_known_name=(avoid[0] if avoid else None),
            )

        child_enc = None
        if self._keyring is not None:
            self._keyring.generate_dek(child_identity.entity_id)
            child_enc = self._encryptor_for(child_identity.entity_id)

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
                    if child_enc is not None:
                        reencrypt_artifacts(
                            src, dst,
                            src_encryptor=parent_enc,
                            dst_encryptor=child_enc,
                        )
                    else:
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
        save_snapshot(self._root, child, encryptor=child_enc)
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
        module_weights_from: str | Mapping[str, str] | None = None,
    ) -> ForkSnapshot:
        """Merge two snapshots into a new one; never modifies either parent.

        Each module in ``MODULE_WEIGHT_GROUPS`` has its weight group taken whole
        from one parent: the group is copied without a choice when it is equal
        in both parents or held by one only; otherwise ``module_weights_from``
        must name the parent ('a', 'b', or a mapping naming each such module),
        or merge raises ``ModuleWeightsChoiceRequiredError``. The rest of the
        module's state merges by its strategy, which never sees a weight key; a
        strategy that fails for such a module raises
        ``ModuleMergeStrategyError``. Nothing is written when merge raises.
        """
        if world_model_from is not None and world_model_from not in ("a", "b"):
            raise ValueError("world_model_from must be 'a', 'b', or None")
        weights_choice = _normalise_weights_choice(module_weights_from)
        enc_a = None
        enc_b = None
        if self._keyring is not None:
            sidecar_a = read_identity_sidecar(snapshot_dir(self._root, snapshot_a_id))
            sidecar_b = read_identity_sidecar(snapshot_dir(self._root, snapshot_b_id))
            if sidecar_a is not None:
                enc_a = self._encryptor_for(sidecar_a.entity_id)
            if sidecar_b is not None:
                enc_b = self._encryptor_for(sidecar_b.entity_id)
        snap_a = load_snapshot(self._root, snapshot_a_id, encryptor=enc_a)
        snap_b = load_snapshot(self._root, snapshot_b_id, encryptor=enc_b)
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

        a_ph_dir = find_artifacts_dir(self._root, snap_a.id, "world_model")
        b_ph_dir = find_artifacts_dir(self._root, snap_b.id, "world_model")
        a_has = a_ph_dir.is_dir() and not a_ph_dir.is_symlink()
        b_has = b_ph_dir.is_dir() and not b_ph_dir.is_symlink()
        if a_has and b_has and world_model_from is None:
            raise WorldModelChoiceRequiredError(
                "both parents carry a world model; merge cannot average "
                "two world models — pass world_model_from='a' or 'b' to choose "
                "which parent's world model continues"
            )
        all_strategies = dict(self._strategies)
        if strategies:
            all_strategies.update(strategies)

        all_names = set(snap_a.modules) | set(snap_b.modules)
        # A parent's serialize-error marker never reaches the merged state.
        modules_a = {n: _without_serialize_error(st) for n, st in snap_a.modules.items()}
        modules_b = {n: _without_serialize_error(st) for n, st in snap_b.modules.items()}
        serialize_errors = {
            name: [
                p
                for p, mods in (("a", snap_a.modules), ("b", snap_b.modules))
                if isinstance(mods.get(name), dict) and _SERIALIZE_ERROR_KEY in mods[name]
            ]
            for name in sorted(all_names)
        }
        serialize_errors = {n: ps for n, ps in serialize_errors.items() if ps}

        # Which parent each module's weight group comes from, decided before any
        # strategy runs or anything is written.
        weight_sources: dict[str, tuple[str, dict[str, Any]]] = {}
        weight_record: dict[str, dict[str, str]] = {}
        needs_choice: dict[str, tuple[str, ...]] = {}
        for name in sorted(all_names):
            keys = MODULE_WEIGHT_GROUPS.get(name)
            if keys is None:
                continue
            group_a = _weight_group(modules_a.get(name), keys)
            group_b = _weight_group(modules_b.get(name), keys)
            if group_a is None and group_b is None:
                continue
            parent, reason, holders = _weight_source(name, group_a, group_b)
            if parent is None:
                parent = (
                    weights_choice.get(name)
                    if isinstance(weights_choice, dict)
                    else weights_choice
                )
                if parent is None:
                    needs_choice[name] = holders
                    continue
            weight_sources[name] = (parent, group_a if parent == "a" else group_b)
            weight_record[name] = {"from": parent, "reason": reason}
        if needs_choice:
            raise ModuleWeightsChoiceRequiredError(needs_choice)

        # The world model's module state (its backend, engine, observation size
        # and checkpoint metadata) travels with its weights: whole from the
        # parent whose world-model artifacts continue, never union-merged.
        wm_name = legacy_aliases.map_module_key("world_model")
        if a_has and b_has:
            wm_parent, wm_reason = world_model_from, "chosen"
        elif a_has or b_has:
            wm_parent, wm_reason = ("a" if a_has else "b"), "one-sided"
        else:
            wm_parent, wm_reason = None, ""
        if wm_name in all_names:
            holder = "a" if modules_a.get(wm_name) is not None else "b"
            if wm_parent is None:
                # No world-model weights in either parent: the state is
                # configuration metadata only and is taken from the parent
                # that holds it, a when both do.
                wm_parent, wm_reason = holder, "no world-model weights"
            elif (modules_a if wm_parent == "a" else modules_b).get(wm_name) is None:
                # The weights' parent recorded no world-model module state; the
                # state (metadata only) comes from the other parent.
                wm_parent, wm_reason = holder, "the weights' parent holds no module state"
            weight_record[wm_name] = {"from": wm_parent, "reason": wm_reason}

        merged_modules: dict[str, dict[str, Any]] = {}
        for name in sorted(all_names):
            strat = all_strategies.get(name, self._default_strategy)
            state_a = modules_a.get(name)
            state_b = modules_b.get(name)
            if name == wm_name:
                merged_modules[name] = copy.deepcopy(
                    state_a if weight_record[name]["from"] == "a" else state_b
                )
                continue
            keys = MODULE_WEIGHT_GROUPS.get(name)
            if keys is None:
                try:
                    merged_modules[name] = strat.merge(state_a, state_b)
                except Exception as exc:
                    log.warning("merge strategy for %s failed: %s", name, exc)
                    merged_modules[name] = state_a if state_a is not None else (state_b or {})
                continue
            # A weight-bearing module: the strategy merges the rest of its state
            # and never sees a weight key; a failure refuses the whole merge.
            try:
                rest = dict(
                    strat.merge(_without_group(state_a, keys), _without_group(state_b, keys))
                )
            except Exception as exc:
                log.warning("merge strategy for %s failed: %s", name, exc, exc_info=True)
                raise ModuleMergeStrategyError(name, exc) from exc
            for key in keys:
                rest.pop(key, None)
            source = weight_sources.get(name)
            if source is not None:
                rest.update(copy.deepcopy(source[1]))
            merged_modules[name] = rest

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
            "module_weights_from": weight_record,
        }
        if serialize_errors:
            # Which parents' module states were serialize-error markers; the
            # merged state holds only what the other parent captured.
            combined_meta["serialize_errors_dropped"] = serialize_errors
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
        a_paths = _artifact_dirs_by_module(a_root)
        b_paths = _artifact_dirs_by_module(b_root)
        sources: dict[str, str] = {}
        for name in sorted(a_paths.keys() | b_paths.keys()):
            if name == legacy_aliases.map_module_key("world_model") and a_has and b_has:
                chosen = "a" if world_model_from == "a" else "b"
                src = a_ph_dir if chosen == "a" else b_ph_dir
            elif name in a_paths:
                chosen = "a"
                src = a_paths[name]
            else:
                chosen = "b"
                src = b_paths[name]
            dst = artifacts_dir(self._root, merged.id, name)
            if src.is_symlink():
                log.warning("skipping symlinked artifact directory: %s", src)
                continue
            if not src.is_dir():
                continue
            try:
                if enc_a is not None:
                    src_enc = enc_a if chosen == "a" else enc_b
                    reencrypt_artifacts(
                        src, dst,
                        src_encryptor=src_enc,
                        dst_encryptor=enc_a,
                    )
                else:
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
        save_snapshot(self._root, merged, encryptor=enc_a)
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
        enc = None
        if self._keyring is not None:
            sidecar = read_identity_sidecar(snapshot_dir(self._root, snapshot_id))
            if sidecar is not None:
                enc = self._encryptor_for(sidecar.entity_id)
        return load_snapshot(self._root, snapshot_id, encryptor=enc)


def merger_from_name(
    name: str,
    *,
    config_section: dict[str, Any] | None = None,
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

    The real merger runs the merge and both merged-adapter checks in a
    child process; the section's ``capability_probe_path`` and
    ``abliteration_probe_path`` (empty selects the bundled probe sets) and
    ``merge_timeout_s`` configure it. Nothing is loaded in this process.
    """
    if name == "fake":
        return FakeAdapterMerger()
    if name in ("ties_dare", "auto"):
        from kaine.lifecycle.adapter_merge import (
            DEFAULT_MERGE_TIMEOUT_S,
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
            capability_probe_path=(
                str(section.get("capability_probe_path", "")).strip() or None
            ),
            abliteration_probe_path=(
                str(section.get("abliteration_probe_path", "")).strip() or None
            ),
            merge_timeout_s=float(
                section.get("merge_timeout_s", DEFAULT_MERGE_TIMEOUT_S)
            ),
        )

        return TiesDareAdapterMerger(cfg)
    raise ValueError(
        f"unknown adapter_merger {name!r}: known values are 'fake', 'ties_dare', 'auto'"
    )
