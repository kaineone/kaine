# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Parity of the ONNX and dynamic-int8 audition exports against torch, on the real weights."""

from __future__ import annotations

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("onnx")

import torch  # noqa: E402

from kaine.model_paths import models_dir  # noqa: E402
from kaine.modules.audition import onnx_export  # noqa: E402
from kaine.modules.audition.ssl_encoders import PINS, verify_weights  # noqa: E402


def _weights_available(name: str) -> bool:
    try:
        verify_weights(name, models_dir() / PINS[name][2])
        return True
    except (FileNotFoundError, ValueError):
        return False


_skip_no_dasheng = pytest.mark.skipif(
    not _weights_available("dasheng"), reason="dasheng weights not fetched"
)
_skip_no_wavjepa = pytest.mark.skipif(
    not _weights_available("wavjepa"), reason="wavjepa weights not fetched"
)


def _weights_dir(name: str):
    return models_dir() / PINS[name][2]


def _assert_int8_close(report: dict[str, float]) -> None:
    # Per-element int8 error on real weights reaches ~0.3 (measured), so an
    # elementwise atol of 1e-2 cannot hold; bound the mean error and the
    # pooled-embedding direction instead.
    assert report["mean_abs"] < 0.1, report
    assert report["pooled_cosine"] > 0.99, report


@pytest.mark.slow
@_skip_no_dasheng
def test_dasheng_onnx_parity(tmp_path):
    torch.manual_seed(0)
    path = onnx_export.export_dasheng(_weights_dir("dasheng"), tmp_path / "dasheng.onnx")
    module = onnx_export.build_dasheng_module(_weights_dir("dasheng"))
    sample = onnx_export.dasheng_sample_input(batch=2, frames=400)
    assert onnx_export.verify_parity(module, path, sample, atol=1e-5)


@pytest.mark.slow
@_skip_no_wavjepa
def test_wavjepa_onnx_parity(tmp_path):
    torch.manual_seed(0)
    path = onnx_export.export_wavjepa(_weights_dir("wavjepa"), tmp_path / "wavjepa.onnx")
    module = onnx_export.build_wavjepa_module(_weights_dir("wavjepa"))
    sample = onnx_export.wavjepa_sample_input(batch=2)
    assert onnx_export.verify_parity(module, path, sample, atol=1e-5)


@pytest.mark.slow
@_skip_no_dasheng
def test_dasheng_int8_parity(tmp_path):
    torch.manual_seed(0)
    path = onnx_export.export_dasheng(_weights_dir("dasheng"), tmp_path / "dasheng.onnx")
    q = onnx_export.quantize_dynamic_int8(path, tmp_path / "dasheng.int8.onnx")
    module = onnx_export.build_dasheng_module(_weights_dir("dasheng"))
    sample = onnx_export.dasheng_sample_input(batch=1, frames=400)
    _assert_int8_close(onnx_export.parity_report(module, q, sample))


@pytest.mark.slow
@_skip_no_wavjepa
def test_wavjepa_int8_parity(tmp_path):
    torch.manual_seed(0)
    path = onnx_export.export_wavjepa(_weights_dir("wavjepa"), tmp_path / "wavjepa.onnx")
    q = onnx_export.quantize_dynamic_int8(path, tmp_path / "wavjepa.int8.onnx")
    module = onnx_export.build_wavjepa_module(_weights_dir("wavjepa"))
    sample = onnx_export.wavjepa_sample_input(batch=1)
    _assert_int8_close(onnx_export.parity_report(module, q, sample))
