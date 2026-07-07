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
DEFAULT_INTERNVIDEO_NEXT_MODEL_ID: str = "revliter/internvideo_next_base_p14_res224_f16"

# The shipped default encoder backend. Stays "dinov2" — a real, working encoder —
# until Phase 2 of the topos-temporal-video-encoder change implements the
# InternVideo-Next clip forward pass; the default flip to "internvideo_next"
# happens THEN (no pretend processes: never ship a stub as the default path).
DEFAULT_ENCODER_BACKEND: str = "dinov2"
ENCODER_BACKENDS: tuple[str, ...] = ("dinov2", "internvideo_next")


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
    except ImportError:
        # numpy is an optional extra; if it's absent the input just can't be a
        # numpy array, so fall through to the "unsupported type" error below.
        pass
    else:
        if isinstance(image, np.ndarray):
            return Image.fromarray(image).convert("RGB")
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


class InternVideoNextEncoder:
    """Frozen, temporally-native InternVideo-Next clip encoder.

    **Phase 1 (this pass) is a scaffold.** The vendoring, the offline-weights
    fetch, the no-remote-code loader
    (:mod:`kaine.modules.topos.internvideo_next_loader`), and this class's wiring
    into the ``encoder_backend`` selector are REAL. The clip forward pass — the
    16-frame ``encode_clip`` that runs ``extract_features`` and pools
    ``[1, 4096, 768] → 768`` — is implemented in Phase 2.

    Until Phase 2, ``load``/``encode`` raise ``NotImplementedError`` (fail
    honestly). This backend NEVER returns a fake/zero/simulated embedding, and it
    is NOT the shipped default (that stays ``DINOv2Encoder``). Selecting it before
    Phase 2 is a loud, explicit error — by design (no pretend processes).
    """

    def __init__(
        self,
        model_id: str = DEFAULT_INTERNVIDEO_NEXT_MODEL_ID,
        *,
        device_preference: str | None = "auto",
        weights_dir: Any = None,
    ) -> None:
        from kaine.modules.topos.internvideo_next_loader import (
            DEFAULT_WEIGHTS_DIR,
            PINNED_REVISION,
        )

        self._model_id = model_id
        self._device_preference = device_preference
        self._device = "cpu"
        self._weights_dir = weights_dir if weights_dir is not None else DEFAULT_WEIGHTS_DIR
        self._revision = PINNED_REVISION
        self._model: Any = None
        self._latent_dim: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def latent_dim(self) -> int:
        if self._latent_dim is None:
            raise RuntimeError(
                "InternVideo-Next encoder not loaded (Phase 2 implements the clip "
                "forward pass; latent_dim is probed at load)"
            )
        return self._latent_dim

    @property
    def device(self) -> str:
        return self._device

    def _not_implemented(self) -> NotImplementedError:
        return NotImplementedError(
            "InternVideo-Next encoder forward pass lands in Phase 2 of the "
            "topos-temporal-video-encoder change (clip seam + ring buffer + "
            "pooling). Phase 1 ships the vendored code, offline-weights fetch, "
            "no-remote-code loader, and this selector scaffolding only. Until "
            "Phase 2, use encoder_backend='dinov2' (the shipped default). This "
            "backend refuses to return a fake embedding."
        )

    async def load(self) -> None:
        raise self._not_implemented()

    async def encode(self, image: Any) -> list[float]:
        raise self._not_implemented()

    async def shutdown(self) -> None:
        self._model = None


def make_encoder(
    backend: str | None = None,
    *,
    model_id: str | None = None,
    device_preference: str | None = "auto",
    weights_dir: Any = None,
) -> Encoder:
    """Return the encoder for ``backend`` (config ``[topos].encoder_backend``).

    ``"dinov2"`` → :class:`DINOv2Encoder` (the shipped default, a real per-frame
    encoder); ``"internvideo_next"`` → :class:`InternVideoNextEncoder` (the
    temporally-native clip encoder; its forward pass is a Phase-2 stub that fails
    loudly rather than fake a result). ``model_id=None`` selects the per-backend
    default id. Unknown backends raise ``ValueError``."""
    resolved = (backend or DEFAULT_ENCODER_BACKEND).strip().lower()
    if resolved == "dinov2":
        return DINOv2Encoder(
            model_id=model_id or DEFAULT_DINOV2_MODEL_ID,
            device_preference=device_preference,
        )
    if resolved == "internvideo_next":
        return InternVideoNextEncoder(
            model_id=model_id or DEFAULT_INTERNVIDEO_NEXT_MODEL_ID,
            device_preference=device_preference,
            weights_dir=weights_dir,
        )
    raise ValueError(
        f"unknown encoder_backend {resolved!r}; expected one of {ENCODER_BACKENDS}"
    )


def _solid_image(width: int, height: int):
    """Tiny gray image used only to probe latent dim."""
    from PIL import Image

    return Image.new("RGB", (width, height), color=(128, 128, 128))
