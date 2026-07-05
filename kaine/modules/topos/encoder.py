# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Vision encoders for Topos.

The ``Encoder`` protocol is the seam for swapping encoders (DINOv2,
V-JEPA 2, CLIP, future learned encoders) without touching the Topos
module. ``DINOv2Encoder`` is the v1 default per build prompt §2.3 and
loads `facebook/dinov2-small` lazily on first init — the rest of the
package imports without requiring `transformers`.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

DEFAULT_DINOV2_MODEL_ID: str = "facebook/dinov2-small"


@runtime_checkable
class Encoder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def latent_dim(self) -> int: ...

    async def load(self) -> None: ...

    async def encode(self, image: Any) -> list[float]: ...

    async def shutdown(self) -> None: ...


def _coerce_to_pil(image: Any):
    from PIL import Image  # lazy

    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(image))).convert("RGB")
    try:
        import numpy as np  # lazy

        if isinstance(image, np.ndarray):
            return Image.fromarray(image).convert("RGB")
    except Exception:
        pass
    raise TypeError(
        f"unsupported image type {type(image).__name__}; "
        "expected PIL.Image, bytes, or numpy.ndarray"
    )


class DINOv2Encoder:
    """Frozen DINOv2 small encoder. CLS-token output, 384-dim."""

    def __init__(
        self,
        model_id: str = DEFAULT_DINOV2_MODEL_ID,
        *,
        device_preference: str | None = "auto",
    ) -> None:
        self._model_id = model_id
        self._device_preference = device_preference
        self._device = "cpu"
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._latent_dim: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def latent_dim(self) -> int:
        if self._latent_dim is None:
            raise RuntimeError("encoder not loaded yet; call await load() first")
        return self._latent_dim

    @property
    def device(self) -> str:
        return self._device

    async def load(self) -> None:
        if self._model is not None:
            return
        import asyncio

        # Suppress HuggingFace telemetry before any from_pretrained call,
        # matching kaine/text_embedding.py (CAL no-outbound guarantee).
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

        from kaine.hardware import resolve_device

        # resolve_device falls back with a warning if the operator's
        # config asks for cuda:1 on a single-GPU host, instead of crashing.
        self._device = resolve_device(self._device_preference)

        def _load_sync():
            import torch
            from transformers import AutoImageProcessor, AutoModel

            processor = AutoImageProcessor.from_pretrained(self._model_id)
            model = AutoModel.from_pretrained(self._model_id)
            model.eval()
            for p in model.parameters():
                p.requires_grad_(False)
            model.to(self._device)
            return torch, processor, model

        self._torch, self._processor, self._model = await asyncio.to_thread(_load_sync)
        # Probe latent dim with a dummy forward.
        dummy = self._processor(
            images=_coerce_to_pil(_solid_image(8, 8)), return_tensors="pt"
        )
        dummy = {k: v.to(self._device) for k, v in dummy.items()}
        with self._torch.no_grad():
            out = self._model(**dummy)
        self._latent_dim = int(out.last_hidden_state.shape[-1])
        log.info(
            "Topos encoder %s loaded on %s; latent dim %d",
            self._model_id,
            self._device,
            self._latent_dim,
        )

    async def encode(self, image: Any) -> list[float]:
        if self._model is None:
            await self.load()
        import asyncio

        pil = _coerce_to_pil(image)

        def _forward_sync() -> list[float]:
            assert self._processor is not None and self._model is not None
            inputs = self._processor(images=pil, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with self._torch.no_grad():
                outputs = self._model(**inputs)
            cls = outputs.last_hidden_state[:, 0, :].squeeze(0)
            return [float(x) for x in cls.tolist()]

        return await asyncio.to_thread(_forward_sync)

    async def shutdown(self) -> None:
        # transformers models are reclaimed by GC; nothing explicit to do.
        self._model = None
        self._processor = None


def _solid_image(width: int, height: int):
    """Tiny gray image used only to probe latent dim."""
    from PIL import Image

    return Image.new("RGB", (width, height), color=(128, 128, 128))
