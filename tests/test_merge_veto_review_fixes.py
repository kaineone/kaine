# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Review-fix regression tests for the adapter-merge veto path.

These tests exercise the fail-closed fixes for empty/missing capability
probe sets, out-of-range scores, malformed verdicts, BaseException
cleanup, output-directory collision avoidance, and threshold validation.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from kaine.lifecycle.adapter_merge import (
    TiesDareAdapterMerger,
    TiesDareMergeConfig,
)
from kaine.modules.hypnos.capability_eval import (
    LocalProbeSetCapabilityEval,
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
    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self.calls = 0

    async def eval(self, model, tokenizer):
        score = self._scores[self.calls]
        self.calls += 1
        return score


def _loader_for(path: str):
    return (f"model-for-{path}", f"tok-for-{path}")


class PassAbliteration:
    async def score(self, model, tokenizer):
        return SimpleNamespace(
            passed=True,
            failed_probe=None,
            matched_pattern=None,
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


def test_empty_capability_probe_set_rejects(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    empty_probe = tmp_path / "empty.jsonl"
    empty_probe.write_text("", encoding="utf-8")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=LocalProbeSetCapabilityEval(
            probe_path=empty_probe, require_probes=True
        ),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "EmptyCapabilityProbeSetError" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_missing_capability_probe_file_rejects(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    missing_probe = tmp_path / "does_not_exist.jsonl"
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=LocalProbeSetCapabilityEval(
            probe_path=missing_probe, require_probes=True
        ),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "EmptyCapabilityProbeSetError" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_require_probes_default_keeps_zero_score(tmp_path: Path):
    missing = tmp_path / "missing.jsonl"
    score = asyncio.run(
        LocalProbeSetCapabilityEval(probe_path=missing).eval(None, None)
    )
    assert score == 0.0


@pytest.mark.parametrize("bad_score", [1.5, True])
def test_out_of_range_score_rejects(tmp_path: Path, bad_score):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, bad_score]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    assert "outside [0, 1]" in meta["adapter_merge_rejected"]
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_malformed_verdict_rejects_and_cleans_up(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")

    class BadAbliteration:
        async def score(self, model, tokenizer):
            return object()

    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, 0.78]),
        abliteration_scorer=BadAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_none_score_rejects_and_cleans_up(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, None]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert meta["adapter_merge"] == "ties_dare"
    assert "adapter_merge_rejected" in meta
    _assert_output_cleaned(tmp_path)
    assert set(paths) == {str(a), str(b)}


def test_base_exception_in_checks_removes_merged_dir(tmp_path: Path, monkeypatch):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, 0.78]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )

    def _raise(*, merged_dir, parent_adapters):
        raise KeyboardInterrupt()

    monkeypatch.setattr(merger, "_check_merged_adapter", _raise)

    with pytest.raises(KeyboardInterrupt):
        merger.merge([str(a)], [str(b)])

    _assert_output_cleaned(tmp_path)


def test_two_merges_same_second_do_not_collide(tmp_path: Path, monkeypatch):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    fixed_ts = "20230101T000000"
    monkeypatch.setattr(
        "kaine.lifecycle.adapter_merge.time", SimpleNamespace(strftime=lambda _fmt: fixed_ts)
    )

    merger = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, 0.78]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths1, meta1 = merger.merge([str(a)], [str(b)])
    assert meta1["merge_timestamp"] == fixed_ts

    # A second merge in the same "second" must still produce a distinct path.
    merger2 = TiesDareAdapterMerger(
        _cfg(tmp_path),
        backend=FakeBackend(),
        capability_eval=ScoreEval([0.8, 0.8, 0.78]),
        abliteration_scorer=PassAbliteration(),
        model_loader=_loader_for,
    )
    paths2, meta2 = merger2.merge([str(a)], [str(b)])
    assert meta2["merge_timestamp"] == fixed_ts

    assert len(paths1) == 1
    assert len(paths2) == 1
    assert paths1[0] != paths2[0]
    assert Path(paths1[0]).exists()
    assert Path(paths2[0]).exists()


@pytest.mark.parametrize(
    "threshold, ok",
    [
        (1.0, False),
        (2.0, False),
        (-0.1, False),
        (float("nan"), False),
        (True, False),
        (0.0, True),
        (0.05, True),
    ],
)
def test_threshold_validation(tmp_path: Path, threshold: float, ok: bool):
    if ok:
        _cfg(tmp_path, capability_loss_threshold=threshold)
    else:
        with pytest.raises(ValueError):
            _cfg(tmp_path, capability_loss_threshold=threshold)


def test_nexus_factory_requires_probes(tmp_path: Path, monkeypatch):
    import kaine.security.crypto as _crypto
    from kaine.nexus.__main__ import _build_fork_manager

    monkeypatch.setattr(_crypto, "install_from_section", lambda section: None)

    manager, reason = _build_fork_manager(
        lifecycle_cfg_loader=lambda: {
            "adapter_merger": "ties_dare",
            "adapter_merge": {
                "base_model_path": "/models/base",
                "output_dir": str(tmp_path / "m"),
            },
            "snapshots_path": str(tmp_path / "forks"),
        },
        encryption_section_loader=lambda: {},
    )

    assert reason is None
    assert manager is not None
    assert manager._adapter_merger._capability_eval._require_probes is True
