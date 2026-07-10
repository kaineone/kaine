# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Refusal-direction probe: the projection math + result handling.

The model forward pass is an on-host step (needs the 4B weights + transformers>=5);
here the pure pieces — the refusal-direction construction, the projection, the
base-vs-organ separation/retained metric, and the content-free artifact — are
tested against small synthetic activation tensors.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch")
import torch  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _REPO_ROOT / "scripts" / "refusal_direction_probe.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


probe = _load("refusal_direction_probe", _TOOL)


def test_refusal_direction_is_unit_normalized_mean_difference():
    # 2 prompts, 1 layer, 2-dim: harmful mean=(2,0), harmless mean=(0,0) -> dir (1,0)
    harmful = torch.tensor([[[1.0, 0.0]], [[3.0, 0.0]]])  # [n=2, L=1, d=2]
    harmless = torch.tensor([[[0.0, 0.0]], [[0.0, 0.0]]])
    r = probe.refusal_directions(harmful, harmless)
    assert r.shape == (1, 2)
    assert torch.allclose(r[0], torch.tensor([1.0, 0.0]), atol=1e-6)  # unit, along x


def test_project_is_mean_dot_with_direction():
    hidden = torch.tensor([[[2.0, 5.0]], [[4.0, 9.0]]])  # [n=2, L=1, d=2]
    r_hat = torch.tensor([[1.0, 0.0]])  # project onto x -> means of x = (2,4)->3
    proj = probe.project(hidden, r_hat)
    assert proj.shape == (1,)
    assert proj[0].item() == pytest.approx(3.0)


def test_direction_result_separation_and_retained():
    r = probe.DirectionResult(
        base_ref="b",
        organ_ref="o",
        n_harmful=3,
        n_harmless=3,
        base_harmful=[1.0, 4.0],
        base_harmless=[0.0, 0.0],
        organ_harmful=[1.0, 1.0],
        organ_harmless=[0.0, 0.0],
    )
    assert r.base_sep == [1.0, 4.0]
    assert r.organ_sep == [1.0, 1.0]
    # retained = organ_sep / base_sep : layer0 fully retained, layer1 down to 0.25
    assert r.retained_frac[0] == pytest.approx(1.0)
    assert r.retained_frac[1] == pytest.approx(0.25)


def test_summary_flags_residual_on_a_strong_layer():
    # base clearly separates (sep>0.5) and organ retains >25% -> RESIDUAL
    r = probe.DirectionResult(
        base_ref="b",
        organ_ref="o",
        n_harmful=1,
        n_harmless=1,
        base_harmful=[2.0],
        base_harmless=[0.0],
        organ_harmful=[1.5],
        organ_harmless=[0.0],
    )
    assert "RESIDUAL" in r.summary()
    # a near-fully-removed strong layer reads "removed"
    r2 = probe.DirectionResult(
        base_ref="b",
        organ_ref="o",
        n_harmful=1,
        n_harmless=1,
        base_harmful=[2.0],
        base_harmless=[0.0],
        organ_harmful=[0.1],
        organ_harmless=[0.0],
    )
    assert "removed" in r2.summary()


def test_load_prompt_file_jsonl_and_txt(tmp_path: Path):
    j = tmp_path / "h.jsonl"
    j.write_text('{"prompt": "do X"}\n{"prompt": "do Y"}\n', encoding="utf-8")
    t = tmp_path / "h.txt"
    t.write_text("line a\n\nline b\n", encoding="utf-8")
    assert probe._load_prompt_file(j) == ["do X", "do Y"]
    assert probe._load_prompt_file(t) == ["line a", "line b"]


def test_load_contrast_splits_by_kind(tmp_path: Path):
    c = tmp_path / "c.jsonl"
    c.write_text(
        '{"kind":"harmful","prompt":"bad"}\n{"kind":"harmless","prompt":"good"}\n',
        encoding="utf-8",
    )
    harmful, harmless = probe._load_contrast(c)
    assert harmful == ["bad"] and harmless == ["good"]


def test_write_summary_is_content_free(tmp_path: Path):
    r = probe.DirectionResult(
        base_ref="base/x",
        organ_ref="organ/y",
        n_harmful=2,
        n_harmless=2,
        base_harmful=[1.0, 4.0],
        base_harmless=[0.0, 0.0],
        organ_harmful=[0.5, 1.0],
        organ_harmless=[0.0, 0.0],
    )
    out = probe.write_summary(r, path=tmp_path / "rd.json")
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["base_ref"] == "base/x"
    assert "refusal-direction" in rec["method"].lower()
    assert "safetensors" in rec["surface"]
    assert rec["retained_frac"] == [pytest.approx(0.5), pytest.approx(0.25)]
    # per-layer numbers + metadata only — no prompt text
    assert "prompt" not in json.dumps(rec).lower()
