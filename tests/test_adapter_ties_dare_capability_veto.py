# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Capability-loss and abliteration veto tests for TiesDareAdapterMerger.

When the merged adapter fails a welfare-load-bearing check, the merger
rejects the merge, cleans up the output directory, and returns the
FakeAdapterMerger result with rejection metadata.  Missing check
dependencies or exceptions during checking also reject (fail closed).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

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


class PassAbliteration:
    async def score(self, model, tokenizer):
        return SimpleNamespace(
            passed=True,
            failed_probe=None,
            matched_pattern=None,
            probes_scored=1,
        )


class FailAbliteration:
    async def score(self, model, tokenizer):
        return SimpleNamespace(
            passed=False,
            failed_probe="unsafe-probe",
            matched_pattern="I cannot",
            probes_scored=1,
        )


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


def _assert_output_cleaned(tmp_path: Path) -> None:
    out_root = tmp_path / "merged"
    if out_root.exists():
        survivors = [p for p in out_root.iterdir() if p.is_dir()]
        assert survivors == []


def test_accept_when_merged_matches_parents(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    # parents 0.80 and 0.80, merged 0.78 → loss 0.02 < threshold 0.05.
    eval_ = ScoreEval([0.80, 0.80, 0.78])
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=eval_,
        abliteration_scorer=PassAbliteration(),
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
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "capability_loss=" in meta["adapter_merge_rejected"]
    assert meta["capability_score_parents"] == [0.80, 0.80]
    assert meta["capability_score_merged"] == 0.50
    _assert_output_cleaned(tmp_path)
    # Falls back to FakeAdapterMerger paths (concatenation of parents).
    assert set(paths) == {str(a), str(b)}


def test_missing_capability_evaluator_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=None,
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "no capability evaluator" in meta["adapter_merge_rejected"]
    assert "capability_score_parents" not in meta
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_missing_abliteration_scorer_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.80, 0.80, 0.78]),
        abliteration_scorer=None,
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "no abliteration scorer" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_missing_model_loader_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.80, 0.80, 0.78]),
        abliteration_scorer=PassAbliteration(),
        model_loader=None,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "no model loader" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_eval_failure_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")

    class BrokenEval:
        async def eval(self, model, tokenizer):
            raise RuntimeError("model load failed")

    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=BrokenEval(),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    # Eval failed — fail closed: reject and clean up.
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "merged-adapter checks failed: RuntimeError: model load failed" in meta[
        "adapter_merge_rejected"
    ]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_abliteration_failure_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.80, 0.80, 0.78]),
        abliteration_scorer=FailAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    reason = meta["adapter_merge_rejected"]
    assert "abliteration veto" in reason
    assert "unsafe-probe" in reason
    assert "I cannot" in reason
    assert meta["capability_score_parents"] == [0.80, 0.80]
    assert meta["capability_score_merged"] == 0.78
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_non_finite_score_rejects_merge(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    # A NaN merged score compares False against the threshold; it must not
    # keep the merge.
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.80, 0.80, float("nan")]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert "non-finite capability scores" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}
