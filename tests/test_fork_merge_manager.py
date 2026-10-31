# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import inspect
from typing import Any

import pytest

from kaine.lifecycle.manager import (
    FakeAdapterMerger,
    ForkManager,
    merger_from_name,
)


class FakeModule:
    def __init__(self, name: str, initial_state: dict[str, Any] | None = None) -> None:
        self.name = name
        self._state = dict(initial_state or {})

    def serialize(self) -> dict[str, Any]:
        return dict(self._state)

    def deserialize(self, state: dict[str, Any]) -> None:
        self._state = dict(state)


class FakeRegistry:
    def __init__(self, modules: list[FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def test_snapshot_captures_each_module(tmp_path):
    mgr = ForkManager(tmp_path)
    interoception = FakeModule("interoception", {"wellness": 0.92})
    sequence = FakeModule("sequence", {"steps": 17})
    snap = mgr.snapshot(FakeRegistry([interoception, sequence]), label="boot")
    assert snap.id
    assert snap.label == "boot"
    assert snap.parent_id is None
    assert snap.modules["interoception"]["wellness"] == 0.92
    assert snap.modules["sequence"]["steps"] == 17
    assert (tmp_path / snap.id / "snapshot.json").exists()


def test_snapshot_deepcopies_state(tmp_path):
    mgr = ForkManager(tmp_path)
    state = {"nested": {"v": 1}}
    interoception = FakeModule("interoception", state)
    snap = mgr.snapshot(FakeRegistry([interoception]))
    # Mutate after snapshot — must not affect saved state.
    state["nested"]["v"] = 999
    loaded = mgr.load(snap.id)
    assert loaded.modules["interoception"]["nested"]["v"] == 1


def test_snapshot_handles_serialize_error(tmp_path):
    class BoomModule:
        name = "boom"

        def serialize(self):
            raise RuntimeError("nope")

        def deserialize(self, _state):
            pass

    mgr = ForkManager(tmp_path)
    snap = mgr.snapshot(FakeRegistry([BoomModule()]))  # type: ignore[list-item]
    assert "_serialize_error" in snap.modules["boom"]


def test_restore_round_trips_into_fresh_modules(tmp_path):
    mgr = ForkManager(tmp_path)
    src_interoception = FakeModule("interoception", {"wellness": 0.5})
    src_sequence = FakeModule("sequence", {"steps": 42})
    snap = mgr.snapshot(FakeRegistry([src_interoception, src_sequence]))

    fresh_interoception = FakeModule("interoception")
    fresh_sequence = FakeModule("sequence")
    mgr.restore(snap.id, FakeRegistry([fresh_interoception, fresh_sequence]))

    assert fresh_interoception.serialize() == {"wellness": 0.5}
    assert fresh_sequence.serialize() == {"steps": 42}


def test_restore_ignores_module_not_in_snapshot(tmp_path):
    mgr = ForkManager(tmp_path)
    snap = mgr.snapshot(FakeRegistry([FakeModule("interoception", {"wellness": 1.0})]))

    extra = FakeModule("vision", {"latent": "frozen"})
    interoception = FakeModule("interoception")
    mgr.restore(snap.id, FakeRegistry([interoception, extra]))
    # The vision module has no entry → state untouched
    assert extra.serialize() == {"latent": "frozen"}
    assert interoception.serialize() == {"wellness": 1.0}


def test_fork_excludes_shed_modules(tmp_path):
    mgr = ForkManager(tmp_path)
    parent = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule("interoception", {"v": 1}),
                FakeModule("sequence", {"v": 2}),
                FakeModule("vision", {"v": 3}),
            ]
        )
    )
    child = mgr.fork(parent.id, label="no-vision", shed=["vision"])
    assert child.parent_id == parent.id
    assert set(child.modules) == {"interoception", "sequence"}
    assert child.metadata["shed"] == ["vision"]


def test_fork_default_carries_all_modules(tmp_path):
    mgr = ForkManager(tmp_path)
    parent = mgr.snapshot(FakeRegistry([FakeModule("interoception", {"v": 1})]))
    child = mgr.fork(parent.id)
    assert child.parent_id == parent.id
    assert child.modules == parent.modules


def test_merge_invokes_per_module_strategies(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule(
                    "episodic_memory",
                    {
                        "short_term_size": 5,
                        "collection_prefix": "episodic_memory_",
                    },
                ),
                # High-certainty (low-entropy) posterior.
                FakeModule("planning", {"posterior": [[0.9, 0.1]]}),
            ]
        )
    )
    b = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule(
                    "episodic_memory",
                    {
                        "short_term_size": 7,
                        "collection_prefix": "episodic_memory_",
                    },
                ),
                # Low-certainty (high-entropy) posterior — discarded on merge.
                FakeModule("planning", {"posterior": [[0.5, 0.5]]}),
            ]
        )
    )
    merged = mgr.merge(a.id, b.id, label="merge")
    assert merged.parent_id == f"{a.id}+{b.id}"
    assert merged.modules["episodic_memory"]["short_term_size"] == 12
    # One-sided selection keeps the more certain (lower-entropy) fork.
    assert merged.modules["planning"]["posterior"] == [[0.9, 0.1]]
    assert merged.modules["planning"].get("planning.merge_warning") is True
    assert merged.metadata["merged_from"] == [a.id, b.id]


def test_merge_handles_module_present_in_only_one_parent(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(FakeRegistry([FakeModule("episodic_memory", {"short_term_size": 3})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("planning", {"posterior": [[1.0, 0.0]]})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["episodic_memory"]["short_term_size"] == 3
    assert merged.modules["planning"]["posterior"] == [[1.0, 0.0]]


def test_merge_falls_back_to_union_for_unknown_module(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(FakeRegistry([FakeModule("custom", {"x": 1, "y": 2})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("custom", {"y": 99, "z": 3})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["custom"] == {"x": 1, "y": 99, "z": 3}


def test_merge_combines_adapters_via_fake_merger(tmp_path):
    # Pin the no-op merger: the default 'auto' picks the real merger when PEFT is
    # installed, which depends on the host.
    mgr = ForkManager(tmp_path, adapter_merger=FakeAdapterMerger())
    a = mgr.snapshot(
        FakeRegistry([FakeModule("interoception", {"v": 1})]),
        adapters=["/state/sleep/adapters/a"],
    )
    b = mgr.snapshot(
        FakeRegistry([FakeModule("interoception", {"v": 2})]),
        adapters=["/state/sleep/adapters/b"],
    )
    # Both parents have adapters + FakeAdapterMerger → must refuse by default.
    from kaine.lifecycle.manager import UnmergedAdaptersError
    with pytest.raises(UnmergedAdaptersError):
        mgr.merge(a.id, b.id)

    # With explicit allow_unmerged_adapters=True the merge proceeds and records
    # the skip in metadata so the operator-visible record is preserved.
    merged = mgr.merge(a.id, b.id, allow_unmerged_adapters=True)
    assert "/state/sleep/adapters/a" in merged.adapters
    assert "/state/sleep/adapters/b" in merged.adapters
    assert merged.metadata["adapter_merge_skipped"] == "no merger configured"


def test_fake_adapter_merger_deduplicates():
    merger = FakeAdapterMerger()
    merged, meta = merger.merge(["a", "b"], ["b", "c"])
    assert merged == ["a", "b", "c"]
    assert meta["adapter_merge_skipped"]


def test_merger_from_name_resolves_fake():
    assert isinstance(merger_from_name("fake"), FakeAdapterMerger)


def test_merger_from_name_rejects_unknown():
    with pytest.raises(ValueError):
        merger_from_name("ties")


def test_snapshots_are_never_evicted(tmp_path):
    """The fork root holds preserved entities: no count cap deletes any of them."""
    mgr = ForkManager(tmp_path)
    snaps = [mgr.snapshot(FakeRegistry([FakeModule("interoception", {"i": i})])) for i in range(70)]
    forked = mgr.fork(snaps[0].id, label="child")
    merged = mgr.merge(snaps[1].id, snaps[2].id, label="merged")
    expected = {s.id for s in snaps} | {forked.id, merged.id}
    assert set(mgr.list_snapshots()) == expected
    for snap_id in expected:
        assert (tmp_path / snap_id / "snapshot.json").exists()


def test_fork_manager_has_no_retention_parameter():
    params = inspect.signature(ForkManager.__init__).parameters
    assert "max_snapshots_retained" not in params
    # No **kwargs either, so the removed keyword cannot be silently accepted.
    assert all(p.kind is not inspect.Parameter.VAR_KEYWORD for p in params.values())


def test_legacy_retention_key_warns_and_deletes_nothing(tmp_path, caplog):
    import logging

    from kaine.dashboard.__main__ import _build_fork_manager

    root = tmp_path / "forks"

    def lifecycle_loader():
        return {"snapshots_path": str(root), "max_snapshots_retained": 2}

    with caplog.at_level(logging.WARNING, logger="kaine.dashboard"):
        mgr, reason = _build_fork_manager(lifecycle_loader, lambda: {"enabled": False})
    assert reason is None
    assert isinstance(mgr, ForkManager)
    assert any("max_snapshots_retained is ignored" in r.getMessage() for r in caplog.records)
    ids = [mgr.snapshot(FakeRegistry([FakeModule("interoception", {"i": i})])).id for i in range(5)]
    assert set(mgr.list_snapshots()) == set(ids)


def test_legacy_retention_key_zero_or_absent_is_silent(tmp_path, caplog):
    import logging

    from kaine.dashboard.__main__ import _build_fork_manager

    for cfg in ({}, {"max_snapshots_retained": 0}):
        caplog.clear()
        cfg = {"snapshots_path": str(tmp_path / "forks"), **cfg}
        with caplog.at_level(logging.WARNING, logger="kaine.dashboard"):
            _build_fork_manager(lambda cfg=cfg: cfg, lambda: {"enabled": False})
        assert not any("max_snapshots_retained" in r.getMessage() for r in caplog.records)


def test_custom_strategies_override_defaults(tmp_path):
    class AlwaysFortyTwo:
        def merge(self, a, b):
            return {"answer": 42}

    mgr = ForkManager(tmp_path, strategies={"episodic_memory": AlwaysFortyTwo()})
    a = mgr.snapshot(FakeRegistry([FakeModule("episodic_memory", {"short_term_size": 1})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("episodic_memory", {"short_term_size": 2})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["episodic_memory"] == {"answer": 42}
