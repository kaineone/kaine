# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator bring-up test for the real PEFT TIES/DARE merge stack.

Gated behind `KAINE_HAS_PEFT=1`. Skipped by default.

Creates two tiny rank-2 LoRA adapters on a 3-layer linear stub
(no language model — pure peft + torch), runs `add_weighted_adapter`,
and verifies the merged adapter saves and reloads.

Do NOT enable in CI — requires the real `peft` + `torch` install.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("KAINE_HAS_PEFT") != "1",
    reason="set KAINE_HAS_PEFT=1 to run the real PEFT TIES/DARE check",
)


@pytest.mark.asyncio
async def test_real_peft_ties_dare_merge(tmp_path: Path):
    """A minimal integration that doesn't need an LLM. Builds two
    LoRA adapters on a tiny torch model, calls add_weighted_adapter
    directly, and verifies the merged adapter exists on disk."""
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model

    class TinyModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.q_proj = torch.nn.Linear(16, 16, bias=False)
            self.v_proj = torch.nn.Linear(16, 16, bias=False)

        def forward(self, x):
            return self.v_proj(self.q_proj(x))

    base = TinyModel()
    lora_cfg = LoraConfig(
        r=2,
        lora_alpha=4,
        target_modules=["q_proj", "v_proj"],
        bias="none",
    )

    # Adapter A.
    model_a = get_peft_model(base, lora_cfg)
    a_path = tmp_path / "adapter_a"
    model_a.save_pretrained(str(a_path))

    # Adapter B (fresh base so they aren't identical).
    base2 = TinyModel()
    model_b = get_peft_model(base2, lora_cfg)
    b_path = tmp_path / "adapter_b"
    model_b.save_pretrained(str(b_path))

    # Merge via PEFT API directly (this is what TiesDareAdapterMerger
    # ultimately invokes; the wrapper indirection isn't what we're
    # testing here — we just want to know PEFT supports this on the
    # operator's install).
    base3 = TinyModel()
    merged_model = PeftModel.from_pretrained(base3, str(a_path), adapter_name="m0")
    merged_model.load_adapter(str(b_path), adapter_name="m1")
    merged_model.add_weighted_adapter(
        adapters=["m0", "m1"],
        weights=[0.5, 0.5],
        adapter_name="merged",
        combination_type="dare_ties",
        density=0.5,
    )
    merged_model.set_adapter("merged")
    out_dir = tmp_path / "merged_out"
    merged_model.save_pretrained(str(out_dir))

    # Smoke: load it back.
    base4 = TinyModel()
    PeftModel.from_pretrained(base4, str(out_dir / "merged"))
