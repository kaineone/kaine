# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Encoder-protocol level tests.

These don't pull in transformers — the DINOv2Encoder is only exercised
in test_topos_dinov2.py (opt-in via env var).
"""
import pytest

from kaine.modules.topos.encoder import (
    DEFAULT_DINOV2_MODEL_ID,
    DINOv2Encoder,
    Encoder,
)


def test_default_model_id_is_dinov2_small():
    assert DEFAULT_DINOV2_MODEL_ID == "facebook/dinov2-small"


def test_dinov2_encoder_constructed_lazily():
    enc = DINOv2Encoder()
    # Construction does not load weights; latent_dim raises until load()
    assert enc.model_id == DEFAULT_DINOV2_MODEL_ID
    with pytest.raises(RuntimeError):
        _ = enc.latent_dim


# Encoder-protocol members, checked structurally on the CLASS. We avoid
# ``isinstance(enc, Encoder)`` because ``isinstance`` against a
# ``@runtime_checkable`` Protocol invokes data-member property getters on Python
# 3.12.4+, and ``Encoder.latent_dim`` intentionally raises before ``load()`` — so
# isinstance on an unloaded encoder raises instead of returning True (see #65).
# ``hasattr(type(enc), name)`` sees the property descriptor without calling it.
_ENCODER_MEMBERS = (
    "model_id",
    "latent_dim",
    "clip_len",
    "load",
    "encode",
    "encode_clip",
    "shutdown",
)


def _implements_encoder(obj) -> bool:
    return all(hasattr(type(obj), name) for name in _ENCODER_MEMBERS)


def test_dinov2_encoder_satisfies_encoder_protocol():
    enc = DINOv2Encoder()
    assert _implements_encoder(enc)


def test_dinov2_encoder_device_default_is_auto():
    enc = DINOv2Encoder()
    assert enc._device_preference == "auto"
    assert enc.device == "cpu"  # before load(), no device probe


def test_dinov2_encoder_accepts_device_preference():
    enc = DINOv2Encoder(device_preference="cpu")
    assert enc._device_preference == "cpu"
