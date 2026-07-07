# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

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
    soma = FakeModule("soma", {"wellness": 0.92})
    chronos = FakeModule("chronos", {"steps": 17})
    snap = mgr.snapshot(FakeRegistry([soma, chronos]), label="boot")
    assert snap.id
    assert snap.label == "boot"
    assert snap.parent_id is None
    assert snap.modules["soma"]["wellness"] == 0.92
    assert snap.modules["chronos"]["steps"] == 17
    assert (tmp_path / snap.id / "snapshot.json").exists()


def test_snapshot_deepcopies_state(tmp_path):
    mgr = ForkManager(tmp_path)
    state = {"nested": {"v": 1}}
    soma = FakeModule("soma", state)
    snap = mgr.snapshot(FakeRegistry([soma]))
    # Mutate after snapshot — must not affect saved state.
    state["nested"]["v"] = 999
    loaded = mgr.load(snap.id)
    assert loaded.modules["soma"]["nested"]["v"] == 1


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
    src_soma = FakeModule("soma", {"wellness": 0.5})
    src_chronos = FakeModule("chronos", {"steps": 42})
    snap = mgr.snapshot(FakeRegistry([src_soma, src_chronos]))

    fresh_soma = FakeModule("soma")
    fresh_chronos = FakeModule("chronos")
    mgr.restore(snap.id, FakeRegistry([fresh_soma, fresh_chronos]))

    assert fresh_soma.serialize() == {"wellness": 0.5}
    assert fresh_chronos.serialize() == {"steps": 42}


def test_restore_ignores_module_not_in_snapshot(tmp_path):
    mgr = ForkManager(tmp_path)
    snap = mgr.snapshot(FakeRegistry([FakeModule("soma", {"wellness": 1.0})]))

    extra = FakeModule("topos", {"latent": "frozen"})
    soma = FakeModule("soma")
    mgr.restore(snap.id, FakeRegistry([soma, extra]))
    # topos has no entry → state untouched
    assert extra.serialize() == {"latent": "frozen"}
    assert soma.serialize() == {"wellness": 1.0}


def test_fork_excludes_shed_modules(tmp_path):
    mgr = ForkManager(tmp_path)
    parent = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule("soma", {"v": 1}),
                FakeModule("chronos", {"v": 2}),
                FakeModule("topos", {"v": 3}),
            ]
        )
    )
    child = mgr.fork(parent.id, label="no-topos", shed=["topos"])
    assert child.parent_id == parent.id
    assert set(child.modules) == {"soma", "chronos"}
    assert child.metadata["shed"] == ["topos"]


def test_fork_default_carries_all_modules(tmp_path):
    mgr = ForkManager(tmp_path)
    parent = mgr.snapshot(FakeRegistry([FakeModule("soma", {"v": 1})]))
    child = mgr.fork(parent.id)
    assert child.parent_id == parent.id
    assert child.modules == parent.modules


def test_merge_invokes_per_module_strategies(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule(
                    "mnemos",
                    {
                        "short_term_size": 5,
                        "collection_prefix": "mnemos_",
                    },
                ),
                # High-certainty (low-entropy) posterior.
                FakeModule("nous", {"posterior": [[0.9, 0.1]]}),
            ]
        )
    )
    b = mgr.snapshot(
        FakeRegistry(
            [
                FakeModule(
                    "mnemos",
                    {
                        "short_term_size": 7,
                        "collection_prefix": "mnemos_",
                    },
                ),
                # Low-certainty (high-entropy) posterior — discarded on merge.
                FakeModule("nous", {"posterior": [[0.5, 0.5]]}),
            ]
        )
    )
    merged = mgr.merge(a.id, b.id, label="merge")
    assert merged.parent_id == f"{a.id}+{b.id}"
    assert merged.modules["mnemos"]["short_term_size"] == 12
    # One-sided selection keeps the more certain (lower-entropy) fork.
    assert merged.modules["nous"]["posterior"] == [[0.9, 0.1]]
    assert merged.modules["nous"].get("nous.merge_warning") is True
    assert merged.metadata["merged_from"] == [a.id, b.id]


def test_merge_handles_module_present_in_only_one_parent(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(FakeRegistry([FakeModule("mnemos", {"short_term_size": 3})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("nous", {"posterior": [[1.0, 0.0]]})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["mnemos"]["short_term_size"] == 3
    assert merged.modules["nous"]["posterior"] == [[1.0, 0.0]]


def test_merge_falls_back_to_union_for_unknown_module(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(FakeRegistry([FakeModule("custom", {"x": 1, "y": 2})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("custom", {"y": 99, "z": 3})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["custom"] == {"x": 1, "y": 99, "z": 3}


def test_merge_combines_adapters_via_fake_merger(tmp_path):
    mgr = ForkManager(tmp_path)
    a = mgr.snapshot(
        FakeRegistry([FakeModule("soma", {"v": 1})]),
        adapters=["/state/hypnos/adapters/a"],
    )
    b = mgr.snapshot(
        FakeRegistry([FakeModule("soma", {"v": 2})]),
        adapters=["/state/hypnos/adapters/b"],
    )
    # Both parents have adapters + FakeAdapterMerger → must refuse by default.
    from kaine.lifecycle.manager import UnmergedAdaptersError
    with pytest.raises(UnmergedAdaptersError):
        mgr.merge(a.id, b.id)

    # With explicit allow_unmerged_adapters=True the merge proceeds and records
    # the skip in metadata so the operator-visible record is preserved.
    merged = mgr.merge(a.id, b.id, allow_unmerged_adapters=True)
    assert "/state/hypnos/adapters/a" in merged.adapters
    assert "/state/hypnos/adapters/b" in merged.adapters
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


def test_retention_evicts_oldest_when_over_max(tmp_path):
    mgr = ForkManager(tmp_path, max_snapshots_retained=2)
    snaps = []
    for i in range(4):
        mod = FakeModule("soma", {"i": i})
        snaps.append(mgr.snapshot(FakeRegistry([mod])))
    remaining = set(mgr.list_snapshots())
    assert len(remaining) == 2
    # newest two should remain
    assert snaps[-1].id in remaining
    assert snaps[-2].id in remaining
    assert snaps[0].id not in remaining


def test_retention_disabled_when_max_zero(tmp_path):
    mgr = ForkManager(tmp_path, max_snapshots_retained=0)
    for i in range(3):
        mgr.snapshot(FakeRegistry([FakeModule("soma", {"i": i})]))
    assert len(mgr.list_snapshots()) == 3


def test_custom_strategies_override_defaults(tmp_path):
    class AlwaysFortyTwo:
        def merge(self, a, b):
            return {"answer": 42}

    mgr = ForkManager(tmp_path, strategies={"mnemos": AlwaysFortyTwo()})
    a = mgr.snapshot(FakeRegistry([FakeModule("mnemos", {"short_term_size": 1})]))
    b = mgr.snapshot(FakeRegistry([FakeModule("mnemos", {"short_term_size": 2})]))
    merged = mgr.merge(a.id, b.id)
    assert merged.modules["mnemos"] == {"answer": 42}
