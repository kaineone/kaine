# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for TiesDareAdapterMerger against a FakePeftBackend.

These do NOT load PEFT or torch — the backend is substituted so we
verify the merger's plumbing (combination type, density, weights,
output layout, metadata shape, fallback paths) in isolation.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from kaine.lifecycle.adapter_merge import (
    TiesDareAdapterMerger,
    TiesDareMergeConfig,
    VALID_COMBINATION_TYPES,
)


@pytest.fixture(autouse=True)
def _fake_peft_extras(monkeypatch):
    """Pretend the extras are installed so the availability check passes."""
    for name in ("peft", "torch"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def merge(self, *, base_model_path, adapter_paths, weights,
              combination_type, density, output_dir):
        self.calls.append(
            {
                "base_model_path": base_model_path,
                "adapter_paths": list(adapter_paths),
                "weights": list(weights),
                "combination_type": combination_type,
                "density": density,
                "output_dir": str(output_dir),
            }
        )
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "adapter_model.safetensors").write_text(
            "fake-merged", encoding="utf-8"
        )
        return Path(output_dir)


def _adapter(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    (p / "adapter_model.safetensors").write_text("x", encoding="utf-8")
    return p


def _config(tmp_path: Path, **overrides) -> TiesDareMergeConfig:
    base = {
        "output_dir": tmp_path / "merged",
        "combination_type": "dare_ties",
        "density": 0.5,
        "base_model_path": str(tmp_path / "fake-base"),
    }
    base.update(overrides)
    return TiesDareMergeConfig(**base)


def test_combination_type_validated():
    with pytest.raises(ValueError):
        TiesDareMergeConfig(
            output_dir=Path("/tmp/x"), combination_type="garbage"
        )


def test_density_validated():
    with pytest.raises(ValueError):
        TiesDareMergeConfig(output_dir=Path("/tmp/x"), density=0.0)
    with pytest.raises(ValueError):
        TiesDareMergeConfig(output_dir=Path("/tmp/x"), density=1.5)


def test_valid_combination_types_constant():
    assert "ties" in VALID_COMBINATION_TYPES
    assert "dare_ties" in VALID_COMBINATION_TYPES
    assert "dare_linear" in VALID_COMBINATION_TYPES


def test_merge_calls_backend_with_config_values(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(
        _config(tmp_path, combination_type="ties", density=0.7),
        backend=backend,
    )
    paths, meta = merger.merge([str(a)], [str(b)])
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["combination_type"] == "ties"
    assert call["density"] == pytest.approx(0.7)
    assert call["adapter_paths"] == [str(a), str(b)]
    # Output path is a timestamped subdir under the configured output_dir.
    assert str(call["output_dir"]).startswith(str(tmp_path / "merged"))
    assert len(paths) == 1
    assert meta["adapter_merge"] == "ties_dare"
    assert meta["combination_type"] == "ties"
    assert meta["density"] == pytest.approx(0.7)
    assert meta["input_adapters"] == [str(a), str(b)]
    assert "merge_timestamp" in meta


def test_uniform_weights_when_unconfigured(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    c = _adapter(tmp_path, "adapter_c")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(_config(tmp_path), backend=backend)
    merger.merge([str(a), str(b)], [str(c)])
    weights = backend.calls[0]["weights"]
    assert len(weights) == 3
    assert all(w == pytest.approx(1 / 3) for w in weights)


def test_configured_weights_are_normalized(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(
        _config(tmp_path, weights=[2.0, 3.0]),
        backend=backend,
    )
    merger.merge([str(a)], [str(b)])
    weights = backend.calls[0]["weights"]
    assert weights == pytest.approx([0.4, 0.6])


def test_wrong_length_weights_fall_back_to_uniform(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(
        _config(tmp_path, weights=[1.0, 2.0, 3.0]),  # 3 weights, 2 adapters
        backend=backend,
    )
    merger.merge([str(a)], [str(b)])
    weights = backend.calls[0]["weights"]
    assert weights == pytest.approx([0.5, 0.5])


def test_dedupes_paths_across_parents(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(_config(tmp_path), backend=backend)
    # Same adapter in both parents — must dedupe to a single input.
    paths, meta = merger.merge([str(a)], [str(a)])
    # Only one distinct input; falls through to FakeAdapterMerger.
    assert meta.get("adapter_merge_skipped") == "fewer than 2 distinct adapters"
    assert meta["input_adapters"] == [str(a)]


def test_falls_through_when_paths_missing_on_disk(tmp_path: Path):
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(_config(tmp_path), backend=backend)
    paths, meta = merger.merge(
        ["/nope/a"], ["/nope/b"]
    )
    assert backend.calls == []
    assert "fewer than 2 adapter paths exist on disk" in meta["adapter_merge_skipped"]


def test_falls_through_when_base_model_path_missing(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    cfg = TiesDareMergeConfig(
        output_dir=tmp_path / "merged",
        combination_type="dare_ties",
        density=0.5,
        base_model_path=None,
    )
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(cfg, backend=backend)
    paths, meta = merger.merge([str(a)], [str(b)])
    assert backend.calls == []
    assert meta["adapter_merge_skipped"] == "base_model_path not configured"


def test_falls_through_when_peft_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "peft", None)
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(_config(tmp_path), backend=backend)
    paths, meta = merger.merge([str(a)], [str(b)])
    assert backend.calls == []
    assert "[training]" in meta["adapter_merge_skipped"]


def test_backend_failure_cleans_up_and_falls_back(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")

    class BoomBackend:
        def merge(self, **kw):
            # Create the output dir then raise — verify cleanup.
            Path(kw["output_dir"]).mkdir(parents=True, exist_ok=True)
            (Path(kw["output_dir"]) / "partial").write_text("p", encoding="utf-8")
            raise RuntimeError("nan in merge")

    merger = TiesDareAdapterMerger(_config(tmp_path), backend=BoomBackend())
    paths, meta = merger.merge([str(a)], [str(b)])
    assert "adapter_merge_failed" in meta
    # Output dir should be cleaned.
    out_root = tmp_path / "merged"
    if out_root.exists():
        for child in out_root.iterdir():
            # No leftover partial.
            assert not (child / "partial").exists()


def test_merge_output_path_is_timestamped_subdir(tmp_path: Path):
    a = _adapter(tmp_path, "adapter_a")
    b = _adapter(tmp_path, "adapter_b")
    backend = FakeBackend()
    merger = TiesDareAdapterMerger(_config(tmp_path), backend=backend)
    paths, meta = merger.merge([str(a)], [str(b)])
    out_path = Path(paths[0])
    assert out_path.parent == tmp_path / "merged"
    # Looks like a timestamp (YYYYMMDDTHHmmss).
    assert len(out_path.name) == 15
    assert out_path.name[8] == "T"
