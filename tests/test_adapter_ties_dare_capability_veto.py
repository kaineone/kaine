# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Capability-loss veto tests for TiesDareAdapterMerger.

When the merged adapter scores significantly worse than the mean of
the parent scores, the merger rejects the merge, cleans up the
output directory, and returns the FakeAdapterMerger result with veto
metadata.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from kaine.lifecycle.adapter_merge import (
    TiesDareAdapterMerger,
    TiesDareMergeConfig,
)


@pytest.fixture(autouse=True)
def _fake_peft_extras(monkeypatch):
    for name in ("peft", "torch"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


def _adapter(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    (p / "adapter_model.safetensors").write_text("x", encoding="utf-8")
    return p


class FakeBackend:
    def merge(self, *, output_dir, **kw):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "adapter_model.safetensors").write_text(
            "merged", encoding="utf-8"
        )
        return Path(output_dir)


class ScoreEval:
    """Returns scores in a configured order — useful for simulating
    parent-vs-merged capability gaps."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self.calls = 0

    async def eval(self, model, tokenizer):
        score = self._scores[self.calls]
        self.calls += 1
        return score


def _loader_for(path: str):
    # Return a marker so the eval can see which adapter is loaded.
    return (f"model-for-{path}", f"tok-for-{path}")


def _cfg(tmp_path: Path, **overrides) -> TiesDareMergeConfig:
    base = {
        "output_dir": tmp_path / "merged",
        "combination_type": "dare_ties",
        "density": 0.5,
        "base_model_path": str(tmp_path / "fake-base"),
        "capability_loss_threshold": 0.05,
    }
    base.update(overrides)
    return TiesDareMergeConfig(**base)


def test_accept_when_merged_matches_parents(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    # parents 0.80 and 0.80, merged 0.78 → loss 0.02 < threshold 0.05.
    eval_ = ScoreEval([0.80, 0.80, 0.78])
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=eval_,
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" not in meta
    # Output adapter exists.
    assert len(paths) == 1
    assert Path(paths[0]).exists()


def test_reject_when_merged_drops_too_much(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    # parents 0.80 and 0.80 (mean 0.80), merged 0.50 → loss 0.30 > 0.05.
    eval_ = ScoreEval([0.80, 0.80, 0.50])
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=eval_,
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert "adapter_merge_rejected" in meta
    assert "capability_loss=" in meta["adapter_merge_rejected"]
    assert meta["capability_score_parents"] == [0.80, 0.80]
    assert meta["capability_score_merged"] == 0.50
    # Output dir was cleaned up.
    out_root = tmp_path / "merged"
    if out_root.exists():
        survivors = [p for p in out_root.iterdir() if p.is_dir()]
        assert survivors == []
    # Falls back to FakeAdapterMerger paths (concatenation of parents).
    assert set(paths) == {str(a), str(b)}


def test_skip_veto_when_no_eval_configured(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path), backend=FakeBackend(),
        capability_eval=None,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    # No veto fields when eval is not configured.
    assert "adapter_merge_rejected" not in meta
    assert "capability_score_parents" not in meta


def test_eval_failure_accepts_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")

    class BrokenEval:
        async def eval(self, model, tokenizer):
            raise RuntimeError("model load failed")

    merger = TiesDareAdapterMerger(
        _cfg(tmp_path), backend=FakeBackend(),
        capability_eval=BrokenEval(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    # Eval failed but merge was already done — accept it rather than
    # discard the work. Veto fields absent.
    assert "adapter_merge_rejected" not in meta
    assert meta["adapter_merge"] == "ties_dare"
