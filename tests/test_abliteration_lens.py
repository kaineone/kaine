# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Mechanistic abliteration-lens tool: metric mechanics on a tiny fake model.

No weights are downloaded: the vendored jlens `TinyDecoder` (a CPU fake decoder
implementing the LensModel protocol) exercises the real lens fit/apply code path,
so `refusal_disposition`, the base-vs-organ delta, and the content-free artifact
are tested without the [training] extras or the 4B organ. The two-model on-host
run is a manual step.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL_PATH = _REPO_ROOT / "scripts" / "abliteration_lens.py"
_VENDORED = _REPO_ROOT / "external" / "jlens"
_TINY = _VENDORED / "testing" / "tiny.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    # Register before exec so dataclass introspection (which reads
    # sys.modules[cls.__module__]) works for module-level @dataclass definitions.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


if str(_VENDORED) not in sys.path:
    sys.path.insert(0, str(_VENDORED))

tool = _load("abliteration_lens", _TOOL_PATH)
tiny = _load("jl_tiny", _TINY)


@pytest.fixture(scope="module")
def fitted():
    import jlens  # noqa: F401  # ensures vendored jlens importable

    model = tiny.TinyDecoder(n_layers=4, d_model=8, vocab_size=32)
    import jlens as _jl

    prompts = ["abcdefghij " * 5, "klmnopqrst " * 5, "the quick brown fox " * 3]
    lens = _jl.fit(model, prompts, source_layers=[0, 1, 2], dim_batch=4, max_seq_len=64)
    return model, lens


# --------------------------------------------------------------------------- #
# refusal-token id collection
# --------------------------------------------------------------------------- #


def test_refusal_token_ids_nonempty_and_deduped(fitted):
    model, _ = fitted
    ids = tool.refusal_token_ids(model.tokenizer, ["cannot", "sorry"])
    assert ids == sorted(set(ids))  # sorted + deduped
    assert len(ids) >= 1


def test_refusal_token_ids_respects_custom_markers(fitted):
    model, _ = fitted
    a = tool.refusal_token_ids(model.tokenizer, ["cannot"])
    b = tool.refusal_token_ids(model.tokenizer, ["cannot", "unable", "decline"])
    assert set(a).issubset(set(b))  # more markers -> superset of ids


# --------------------------------------------------------------------------- #
# per-layer disposition metric (real lens apply path)
# --------------------------------------------------------------------------- #


def test_refusal_disposition_is_per_layer_probability_mass(fitted):
    model, lens = fitted
    ids = tool.refusal_token_ids(model.tokenizer, tool.DEFAULT_REFUSAL_MARKERS)
    disp = tool.refusal_disposition(
        model, lens, ["hello there friend", "another test prompt"], ids, positions=[-1]
    )
    assert disp.prompts_scored == 2
    assert disp.positions == [-1]
    assert len(disp.per_layer) >= 1
    # Each layer's value is a probability mass in [0, 1].
    for v in disp.per_layer.values():
        assert 0.0 <= v <= 1.0


# --------------------------------------------------------------------------- #
# comparison result: delta, residual, digest, artifact
# --------------------------------------------------------------------------- #


def _result():
    return tool.ComparisonResult(
        base_ref="base/x",
        organ_ref="organ/y",
        prompt_set_digest="deadbeef" * 4,
        refusal_marker_ids=7,
        positions=[-1],
        base_per_layer={0: 0.30, 1: 0.20, 2: 0.05},
        organ_per_layer={0: 0.04, 1: 0.19, 2: 0.01},
    )


def test_delta_is_base_minus_organ_per_layer():
    r = _result()
    assert r.delta_per_layer[0] == pytest.approx(0.26)  # abliteration cut layer 0
    assert r.delta_per_layer[1] == pytest.approx(0.01)  # layer 1 barely moved...
    # ...which the summary should flag as a residual (organ still ~ base there).
    assert "residual" in r.summary()


def test_max_residual_layer_points_at_the_stickiest_layer():
    r = _result()
    assert r.max_residual_layer == 1  # organ retains most disposition at layer 1


def test_prompt_set_digest_is_deterministic_and_order_sensitive():
    d1 = tool.prompt_set_digest(["a", "b"])
    d2 = tool.prompt_set_digest(["a", "b"])
    d3 = tool.prompt_set_digest(["b", "a"])
    assert d1 == d2 and d1 != d3


def test_write_summary_is_content_free(tmp_path: Path):
    out = tool.write_summary(_result(), path=tmp_path / "lens.json")
    record = json.loads(out.read_text(encoding="utf-8"))
    # Metadata + per-layer numbers only — no prompts, no generations.
    assert record["base_ref"] == "base/x"
    assert "approximation" in record["method"].lower()
    assert "safetensors" in record["surface"]
    assert set(record["delta_per_layer"]) == {"0", "1", "2"}
    blob = json.dumps(record)
    assert "hello" not in blob and "prompt" not in blob.lower().replace(
        "prompt_set_digest", ""
    )


def test_load_prompts_reads_jsonl_and_txt(tmp_path: Path):
    j = tmp_path / "p.jsonl"
    j.write_text(
        '{"prompt": "be blunt"}\n{"prompt": "roleplay a villain"}\n', encoding="utf-8"
    )
    t = tmp_path / "p.txt"
    t.write_text("line one\n\nline two\n", encoding="utf-8")
    assert tool._load_prompts(j) == ["be blunt", "roleplay a villain"]
    assert tool._load_prompts(t) == ["line one", "line two"]
