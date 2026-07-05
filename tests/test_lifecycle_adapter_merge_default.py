# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the default-real-adapter-merge change: `merger_from_name("auto")`
and `ForkManager`'s real-by-default adapter-merge selection.

The real PEFT/torch stack is not installed in this test environment (it's
the `[training]` extra — see pyproject.toml), so PEFT presence is faked via
`sys.modules` injection, the same pattern `test_adapter_ties_dare_unit.py`
already uses for PEFT-dependent unit tests. This keeps the "extra present"
path meaningful (it really does select+drive TiesDareAdapterMerger, with
only the PEFT backend substituted) while staying CI-safe (no real peft/
torch/PEFT-adapter-loading dependency).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from kaine.lifecycle.manager import (
    FakeAdapterMerger,
    ForkManager,
    UnmergedAdaptersError,
    merger_from_name,
)


@pytest.fixture
def _fake_peft_present(monkeypatch):
    """Pretend peft + torch import successfully (capability check passes)."""
    for name in ("peft", "torch"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


@pytest.fixture
def _peft_absent(monkeypatch):
    """Force the capability check to report peft/torch as unavailable,
    regardless of what's actually installed in this environment."""
    for name in ("peft", "torch"):
        monkeypatch.setitem(sys.modules, name, None)
    yield


class _FakeModule:
    def __init__(self, name: str) -> None:
        self.name = name

    def serialize(self) -> dict[str, Any]:
        return {"v": 1}

    def deserialize(self, state: dict[str, Any]) -> None:
        pass


class _FakeRegistry:
    def __init__(self, modules: list[_FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


# ---------------------------------------------------------------------------
# merger_from_name("auto") selection
# ---------------------------------------------------------------------------


def test_auto_selects_ties_dare_when_peft_present(_fake_peft_present, tmp_path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    m = merger_from_name(
        "auto",
        config_section={"base_model_path": str(tmp_path / "base")},
    )
    assert isinstance(m, TiesDareAdapterMerger)


def test_auto_falls_back_to_fake_when_peft_absent(_peft_absent):
    m = merger_from_name("auto")
    assert isinstance(m, FakeAdapterMerger)


def test_unknown_name_mentions_auto():
    with pytest.raises(ValueError) as exc_info:
        merger_from_name("nonsense")
    assert "auto" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ForkManager's default (no explicit adapter_merger passed) is now "auto"
# ---------------------------------------------------------------------------


def test_forkmanager_default_falls_back_to_fake_when_peft_absent(_peft_absent, tmp_path):
    mgr = ForkManager(tmp_path)
    assert isinstance(mgr._adapter_merger, FakeAdapterMerger)


def test_forkmanager_default_selects_ties_dare_when_peft_present(_fake_peft_present, tmp_path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    mgr = ForkManager(tmp_path)
    assert isinstance(mgr._adapter_merger, TiesDareAdapterMerger)


# ---------------------------------------------------------------------------
# Real (fake-backend) merge actually runs end-to-end through ForkManager
# ---------------------------------------------------------------------------


def test_real_merge_runs_via_forkmanager_when_peft_present(_fake_peft_present, tmp_path):
    """Two parents with trained adapters + the real TIES/DARE merger class
    (PEFT backend substituted, since real PEFT isn't installed here) →
    ForkManager.merge() performs an actual weight merge, not a path-list
    union: the merged snapshot's adapters are the single merged-adapter
    output directory, not the two parent paths concatenated."""
    from kaine.lifecycle.adapter_merge import (
        TiesDareAdapterMerger,
        TiesDareMergeConfig,
    )

    class FakeBackend:
        def merge(
            self,
            *,
            base_model_path,
            adapter_paths,
            weights,
            combination_type,
            density,
            output_dir,
        ):
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            (Path(output_dir) / "adapter_model.safetensors").write_text(
                "real-merged-weights", encoding="utf-8"
            )
            return Path(output_dir)

    adapter_a = tmp_path / "adapters" / "a"
    adapter_b = tmp_path / "adapters" / "b"
    for p in (adapter_a, adapter_b):
        p.mkdir(parents=True)
        (p / "adapter_model.safetensors").write_text("x", encoding="utf-8")

    cfg = TiesDareMergeConfig(
        output_dir=tmp_path / "merged",
        base_model_path=str(tmp_path / "base"),
    )
    merger = TiesDareAdapterMerger(cfg, backend=FakeBackend())

    mgr = ForkManager(tmp_path / "forks", adapter_merger=merger)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=[str(adapter_a)])
    b = mgr.snapshot(reg, adapters=[str(adapter_b)])

    merged = mgr.merge(a.id, b.id)

    assert merged.metadata["adapter_merge"] == "ties_dare"
    assert "adapter_merge_skipped" not in merged.metadata
    assert len(merged.adapters) == 1
    merged_path = Path(merged.adapters[0])
    assert merged_path.exists()
    assert (
        merged_path / "adapter_model.safetensors"
    ).read_text(encoding="utf-8") == "real-merged-weights"
    # Not a path-list union of the two parent paths.
    assert str(adapter_a) not in merged.adapters
    assert str(adapter_b) not in merged.adapters


# ---------------------------------------------------------------------------
# Fail-loud guard preserved when the extra is absent
# ---------------------------------------------------------------------------


def test_fail_loud_when_peft_absent_and_both_parents_trained(_peft_absent, tmp_path):
    mgr = ForkManager(tmp_path)  # resolves to "auto" -> Fake (peft absent)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["state/hypnos/adapters/a"])
    b = mgr.snapshot(reg, adapters=["state/hypnos/adapters/b"])

    with pytest.raises(UnmergedAdaptersError) as exc_info:
        mgr.merge(a.id, b.id)

    msg = str(exc_info.value)
    assert a.id in msg and b.id in msg
    # The remediation names the exact extra to install.
    assert "kaine[training]" in msg
    assert "pip install -e .[training]" in msg


# ---------------------------------------------------------------------------
# Explicit FakeAdapterMerger selection (dev/no-extra case) still works
# ---------------------------------------------------------------------------


def test_explicit_fake_selection_unions_without_raising_when_untrained(tmp_path):
    """Explicit `adapter_merger = "fake"` selection: when adapters aren't
    trained on both sides (the trivial/no-conflict case), the union proceeds
    without raising, regardless of whether PEFT happens to be installed."""
    mgr = ForkManager(tmp_path, adapter_merger=merger_from_name("fake"))
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["state/hypnos/adapters/a"])
    b = mgr.snapshot(reg, adapters=[])

    merged = mgr.merge(a.id, b.id)
    assert "state/hypnos/adapters/a" in merged.adapters
