# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.hypnos.adapter_store atomic promotion + retention."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from kaine.modules.hypnos import adapter_store


def _populate_tmp(tmp_dir: Path) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    (tmp_dir / "adapter_model.safetensors").write_text("fake", encoding="utf-8")
    return tmp_dir


def test_promote_renames_and_updates_current(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    tmp = adapter_store.tmp_dir_for(out, "20260530T120000")
    final = adapter_store.final_dir_for(out, "20260530T120000")
    _populate_tmp(tmp)
    promoted = adapter_store.promote(tmp, final)
    assert promoted == final
    assert final.exists()
    assert not tmp.exists()
    current = out / "current"
    assert current.is_symlink()
    assert current.resolve() == final


def test_promote_rejects_existing_final_dir(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    tmp = adapter_store.tmp_dir_for(out, "20260530T120000")
    final = adapter_store.final_dir_for(out, "20260530T120000")
    _populate_tmp(tmp)
    final.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        adapter_store.promote(tmp, final)


def test_promote_swings_current_atomically(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    # First promotion.
    t1 = adapter_store.tmp_dir_for(out, "20260530T120000")
    _populate_tmp(t1)
    adapter_store.promote(t1, adapter_store.final_dir_for(out, "20260530T120000"))
    # Second promotion — `current` must swing without going missing.
    t2 = adapter_store.tmp_dir_for(out, "20260530T121500")
    _populate_tmp(t2)
    f2 = adapter_store.final_dir_for(out, "20260530T121500")
    adapter_store.promote(t2, f2)
    current = out / "current"
    assert current.is_symlink()
    assert current.resolve() == f2


def test_reject_removes_tmp(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    tmp = adapter_store.tmp_dir_for(out, "20260530T120000")
    _populate_tmp(tmp)
    adapter_store.reject(tmp)
    assert not tmp.exists()
    # Idempotent — second call must not raise.
    adapter_store.reject(tmp)


def test_reject_noop_on_missing(tmp_path: Path):
    adapter_store.reject(tmp_path / "never-existed")  # must not raise


def test_list_accepted_excludes_tmp_and_marker(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    (out / "20260530T120000").mkdir()
    (out / "20260530T121500").mkdir()
    (out / "20260530T122500.tmp").mkdir()
    (out / "PENDING_OPERATOR_RELOAD").write_text("x", encoding="utf-8")
    # `current` symlink existing should not appear in the listing either.
    os.symlink("20260530T121500", out / "current")
    items = adapter_store.list_accepted(out)
    names = sorted(p.name for p in items)
    assert names == ["20260530T120000", "20260530T121500"]


def test_prune_keeps_n_evicts_rest(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    stamps = [f"20260530T12{m:02d}00" for m in range(8)]
    for s in stamps:
        (out / s).mkdir()
        # Ensure ordered mtimes.
        time.sleep(0.01)
    # No `current` symlink — anything is fair game.
    evicted = adapter_store.prune(out, keep=3)
    survivors = sorted(p.name for p in adapter_store.list_accepted(out))
    assert len(survivors) == 3
    assert survivors == stamps[-3:]
    assert {p.name for p in evicted} == set(stamps[:5])


def test_prune_never_evicts_current_target(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    # Oldest is the one `current` points at.
    for s in ("20260530T120000", "20260530T121500", "20260530T123000",
              "20260530T124500", "20260530T130000"):
        (out / s).mkdir()
        time.sleep(0.01)
    os.symlink("20260530T120000", out / "current")
    evicted = adapter_store.prune(out, keep=2)
    survivor_names = {p.name for p in adapter_store.list_accepted(out)}
    # `current`'s target stays even though it's the oldest. Cap=2 still
    # honored; the other survivor is the newest. Three middle adapters
    # are evicted.
    assert survivor_names == {"20260530T120000", "20260530T130000"}
    evicted_names = {p.name for p in evicted}
    assert evicted_names == {"20260530T121500", "20260530T123000", "20260530T124500"}


def test_prune_noop_under_cap(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    (out / "a").mkdir()
    (out / "b").mkdir()
    assert adapter_store.prune(out, keep=5) == []


def test_prune_rejects_zero_keep(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    with pytest.raises(ValueError):
        adapter_store.prune(out, keep=0)


def test_current_path_returns_none_when_absent(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    assert adapter_store.current_path(out) is None


def test_current_path_resolves_symlink(tmp_path: Path):
    out = tmp_path / "adapters"
    out.mkdir()
    target = out / "20260530T130000"
    target.mkdir()
    os.symlink("20260530T130000", out / "current")
    assert adapter_store.current_path(out) == target
