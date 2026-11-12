# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""ONNX and dynamic-int8 exports of the acoustic encoders' inference path.

Each encoder is exported as a thin segment module holding only what the runtime
forward pass uses: Dasheng's mel-to-hidden-states encoder, and WavJEPA's student
(context) path with no teacher, decoder or mappers. Weights load through the same
fail-closed ``verify_weights`` + ``_build`` path the runtime wrappers use.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from kaine.modules.audition.ssl_encoders import (
    DashengAcousticEncoder,
    WavJEPAAcousticEncoder,
)

_DEFAULT_OPSET = 17


class DashengSegmentModule(nn.Module):
    """Mel spectrogram [B, n_mels, T] to hidden states [B, patches, 768]."""

    def __init__(self, encoder_module: nn.Module) -> None:
        super().__init__()
        self.encoder = encoder_module

    def forward(self, input_values: torch.Tensor) -> torch.Tensor:
        return self.encoder(torch.unsqueeze(input_values, 1))


class WavJEPASegmentModule(nn.Module):
    """Normalized waveform [B, 1, N] plus padding mask to contextual features."""

    def __init__(self, wavjepa_inner: nn.Module) -> None:
        super().__init__()
        self.extract_audio = wavjepa_inner.extract_audio
        self.feature_norms = wavjepa_inner.feature_norms
        self.post_extraction_mapper = wavjepa_inner.post_extraction_mapper
        self.register_buffer(
            "pos_encoding_encoder", wavjepa_inner.pos_encoding_encoder.detach().clone()
        )
        self.encoder = wavjepa_inner.encoder

    def forward(self, audio: torch.Tensor, padding_mask: torch.Tensor) -> torch.Tensor:
        features = self.feature_norms(self.extract_audio(audio))
        if self.post_extraction_mapper is not None:
            features = self.post_extraction_mapper(features)
        features = features + self.pos_encoding_encoder
        return self.encoder(features, src_key_padding_mask=padding_mask)


def _load_model(cls: type, weights_dir: Path) -> Any:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    wrapper = cls(weights_dir=Path(weights_dir))
    wrapper._load()
    return wrapper._model


def build_dasheng_module(weights_dir: Path) -> DashengSegmentModule:
    model = _load_model(DashengAcousticEncoder, weights_dir)
    return DashengSegmentModule(model.encoder).eval()


def build_wavjepa_module(weights_dir: Path) -> WavJEPASegmentModule:
    model = _load_model(WavJEPAAcousticEncoder, weights_dir)
    return WavJEPASegmentModule(model.model).eval()


def dasheng_sample_input(batch: int = 1, frames: int = 400) -> tuple[torch.Tensor]:
    return (torch.randn(batch, 64, frames),)


def wavjepa_sample_input(batch: int = 1) -> tuple[torch.Tensor, torch.Tensor]:
    audio = torch.randn(batch, 1, 32160)
    return audio, torch.zeros(batch, 200, dtype=torch.bool)


def _export(
    module: nn.Module,
    sample: tuple[torch.Tensor, ...],
    input_names: list[str],
    output_path: Path,
    opset: int,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    axes = {name: {0: "batch"} for name in [*input_names, "hidden_states"]}
    # The fused eval-mode transformer kernel has no ONNX symbolic; trace the
    # decomposed path instead.
    previous = torch.backends.mha.get_fastpath_enabled()
    torch.backends.mha.set_fastpath_enabled(False)
    try:
        with torch.no_grad():
            torch.onnx.export(
                module,
                sample,
                str(output_path),
                input_names=input_names,
                output_names=["hidden_states"],
                dynamic_axes=axes,
                opset_version=opset,
                dynamo=False,
            )
    finally:
        torch.backends.mha.set_fastpath_enabled(previous)
    return output_path


def export_dasheng(weights_dir: Path, output_path: Path, *, opset: int = _DEFAULT_OPSET) -> Path:
    module = build_dasheng_module(weights_dir)
    return _export(module, dasheng_sample_input(), ["input_values"], output_path, opset)


def export_wavjepa(weights_dir: Path, output_path: Path, *, opset: int = _DEFAULT_OPSET) -> Path:
    module = build_wavjepa_module(weights_dir)
    return _export(
        module, wavjepa_sample_input(), ["audio", "padding_mask"], output_path, opset
    )


def quantize_dynamic_int8(onnx_path: Path, output_path: Path) -> Path:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(str(onnx_path), str(output_path), weight_type=QuantType.QUInt8)
    return output_path


def verify_parity(
    torch_module: nn.Module,
    onnx_path: Path,
    sample_input: torch.Tensor | tuple[torch.Tensor, ...],
    *,
    atol: float = 1e-5,
    rtol: float = 1e-4,
) -> bool:
    expected, actual = _run_both(torch_module, onnx_path, sample_input)
    return bool(np.allclose(actual, expected, atol=atol, rtol=rtol))


def parity_report(
    torch_module: nn.Module,
    onnx_path: Path,
    sample_input: torch.Tensor | tuple[torch.Tensor, ...],
) -> dict[str, float]:
    """Error summary for a lossy (int8) export: elementwise error plus the cosine
    similarity of the mean-pooled embeddings, which is what the runtime consumes."""
    expected, actual = _run_both(torch_module, onnx_path, sample_input)
    err = np.abs(actual - expected)
    pe, pa = expected.mean(axis=1), actual.mean(axis=1)
    cos = (pe * pa).sum(axis=1) / (np.linalg.norm(pe, axis=1) * np.linalg.norm(pa, axis=1))
    return {
        "max_abs": float(err.max()),
        "mean_abs": float(err.mean()),
        "pooled_cosine": float(cos.min()),
    }


def _run_both(
    torch_module: nn.Module,
    onnx_path: Path,
    sample_input: torch.Tensor | tuple[torch.Tensor, ...],
) -> tuple[np.ndarray, np.ndarray]:
    import onnxruntime as ort

    inputs = (sample_input,) if isinstance(sample_input, torch.Tensor) else tuple(sample_input)
    with torch.no_grad():
        expected = torch_module(*inputs).cpu().numpy()

    session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    feed = {i.name: t.cpu().numpy() for i, t in zip(session.get_inputs(), inputs, strict=True)}
    (actual,) = session.run(None, feed)
    return expected, actual
