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

# The shipped default encoder backend. Phase 2 of the topos-temporal-video-encoder
# change made the temporally-native InternVideo-Next clip encoder real, so the
# default flipped from "dinov2" to "internvideo_next" (design.md §6, task 6.1):
# a default install loads NO Meta-owned model. DINOv2 stays a selectable,
# Apache-2.0, per-frame fallback (encoder_backend = "dinov2", clip_len = 1).
DEFAULT_ENCODER_BACKEND: str = "internvideo_next"
ENCODER_BACKENDS: tuple[str, ...] = ("dinov2", "internvideo_next")

# InternVideo-Next consumes a fixed 16-frame clip; DINOv2 is per-frame (clip_len 1).
DEFAULT_CLIP_LEN: int = 16
DEFAULT_POOLING: str = "attention"
DEFAULT_CLIP_RESOLUTION: int = 224


@runtime_checkable
class Encoder(Protocol):
    """The swappable Topos vision-encoder seam (topos-temporal-video-encoder).

    An encoder consumes a clip of ``clip_len`` frames and returns one pooled
    latent vector. A per-frame encoder implements the protocol with
    ``clip_len == 1`` (its ``encode_clip`` encodes the most recent frame). The
    per-frame ``encode`` primitive is retained for the spatial-foveation path.
    """

    @property
    def model_id(self) -> str:
        """Identity string of the underlying model (recorded on topos.report)."""

    @property
    def latent_dim(self) -> int:
        """Dimensionality of the pooled latent; known only after ``load()``."""

    @property
    def clip_len(self) -> int:
        """Number of frames the encoder consumes per clip (1 for per-frame)."""

    async def load(self) -> None:
        """Load and freeze the underlying model. Idempotent."""

    async def encode(self, image: Any) -> list[float]:
        """Encode a single frame to a latent (per-frame / foveation path)."""

    async def encode_clip(self, frames: Any) -> list[float]:
        """Encode a clip of exactly ``clip_len`` frames to one pooled vector."""

    async def shutdown(self) -> None:
        """Release the underlying model."""


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
    def clip_len(self) -> int:
        # DINOv2 is a per-frame encoder: a "clip" is a single frame.
        return 1

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

    async def encode_clip(self, frames: Any) -> list[float]:
        """Per-frame fallback: encode the most recent frame of the clip.

        DINOv2 has ``clip_len == 1``, so Topos hands it a 1-frame buffer; this
        encodes ``frames[-1]`` (the current frame), preserving the historical
        per-frame CLS-token behavior behind the clip-native seam."""
        seq = list(frames)
        if not seq:
            raise ValueError("encode_clip requires at least one frame")
        return await self.encode(seq[-1])

    async def shutdown(self) -> None:
        # transformers models are reclaimed by GC; nothing explicit to do.
        self._model = None
        self._processor = None


class InternVideoNextEncoder:
    """Frozen, temporally-native InternVideo-Next clip encoder (the shipped default).

    Consumes a fixed 16-frame clip and returns one **768-dim** pooled clip
    embedding that already encodes motion. Loads a **vendored, revision-pinned**
    copy of the modeling code (``external/internvideo_next/``) plus locally cached
    weights via :func:`kaine.modules.topos.internvideo_next_loader.load_internvideo_next`
    — ``trust_remote_code=False``, ``local_files_only=True``, no runtime network,
    no ``Auto*`` code resolution (design.md §5). Frozen contract (``eval()`` +
    ``requires_grad_(False)``) is applied by the loader; Topos never trains it.

    Pooling ``[1, 4096, 768] → 768``:

    - ``"attention"`` (default) uses the model's **native** attention-pooling head
      (``clip_projector`` / ``AttentionPoolingBlock``, ``clip_embed_dim = 768``),
      reached via ``model(pixel_values)`` — the CLIP-aligned global vector the
      model was trained to summarize a clip with (design.md §2 note).
    - ``"mean"`` mean-pools ``extract_features`` over the 4096-token axis.

    The pooled vector is **not** L2-normalized (task 0.3): the habituation and
    forward-model salience signals carry information in its magnitude.

    Loading the real model requires a CUDA host with the vendored code's deps
    (``einops``, ``timm``, ``flash_attn``, ``easydict`` — the ``[internvideo]``
    extra). Tests inject a fake model/processor via ``load(_model=..., _processor=...)``
    to exercise the pooling + shape pipeline without weights, a GPU, or those deps.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_INTERNVIDEO_NEXT_MODEL_ID,
        *,
        device_preference: str | None = "auto",
        weights_dir: Any = None,
        clip_len: int = DEFAULT_CLIP_LEN,
        pooling: str = DEFAULT_POOLING,
        clip_resolution: int = DEFAULT_CLIP_RESOLUTION,
    ) -> None:
        from kaine.modules.topos.internvideo_next_loader import (
            DEFAULT_WEIGHTS_DIR,
            PINNED_REVISION,
        )

        pooling = str(pooling).strip().lower()
        if pooling not in ("attention", "mean"):
            raise ValueError(
                f"unknown pooling {pooling!r}; expected 'attention' or 'mean'"
            )
        if int(clip_len) < 1:
            raise ValueError("clip_len must be >= 1")

        self._model_id = model_id
        self._device_preference = device_preference
        self._device = "cpu"
        self._weights_dir = weights_dir if weights_dir is not None else DEFAULT_WEIGHTS_DIR
        self._revision = PINNED_REVISION
        self._clip_len = int(clip_len)
        self._pooling = pooling
        self._clip_resolution = int(clip_resolution)
        self._model: Any = None
        self._processor: Any = None
        self._torch: Any = None
        self._latent_dim: int | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def clip_len(self) -> int:
        return self._clip_len

    @property
    def pooling(self) -> str:
        return self._pooling

    @property
    def latent_dim(self) -> int:
        if self._latent_dim is None:
            raise RuntimeError(
                "InternVideo-Next encoder not loaded yet; call await load() first "
                "(latent_dim is probed from a dummy clip forward at load)"
            )
        return self._latent_dim

    @property
    def device(self) -> str:
        return self._device

    async def load(self, *, _model: Any = None, _processor: Any = None) -> None:
        """Load the frozen encoder + processor and probe ``latent_dim``. Idempotent.

        ``_model`` / ``_processor`` inject fakes for tests (no weights / GPU /
        vendored-code deps); production leaves them ``None`` → the offline loader
        and the vendored ``VideoMAEImageProcessor`` config are used."""
        if self._model is not None:
            return
        import asyncio

        # No-outbound guarantee: disable telemetry AND forbid hub reachability
        # before any transformers call (the loader hardens the same env too).
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

        from kaine.hardware import resolve_device

        self._device = resolve_device(self._device_preference)

        def _load_sync():
            import torch

            if _model is not None:
                model = _model
            else:
                from kaine.modules.topos.internvideo_next_loader import (
                    load_internvideo_next,
                )

                model = load_internvideo_next(
                    weights_dir=self._weights_dir,
                    device=self._device,
                    torch_dtype=torch.float16,
                    revision=self._revision,
                )
            processor = _processor if _processor is not None else _load_videomae_processor()
            return torch, model, processor

        self._torch, self._model, self._processor = await asyncio.to_thread(_load_sync)

        # Probe latent_dim with a dummy 16-frame clip forward (same pattern as
        # DINOv2 probing 384 today), so a dim change is discovered at load.
        dummy = [_solid_image(self._clip_resolution, self._clip_resolution)] * self._clip_len
        probe = await asyncio.to_thread(self._forward_clip, dummy)
        self._latent_dim = len(probe)
        log.info(
            "Topos encoder %s loaded on %s; clip_len %d, pooling %s, latent dim %d "
            "(trust_remote_code=False)",
            self._model_id,
            self._device,
            self._clip_len,
            self._pooling,
            self._latent_dim,
        )

    def _forward_clip(self, pil_frames: list[Any]) -> list[float]:
        """Synchronous clip forward + pool → a flat 768-length float list.

        Builds ``pixel_values`` via the VideoMAE processor, orients it to the
        vendored backbone's expected ``[B, C, T, H, W]``, runs the frozen forward
        (native attention pool or mean pool), and returns the pooled vector."""
        torch = self._torch
        inputs = self._processor(pil_frames, return_tensors="pt")
        pixel_values = inputs["pixel_values"]
        # VideoMAE processors emit [B, T, C, H, W]; the vendored PatchEmbed reads
        # [B, C, T, H, W]. Reorient when the channel axis is at index 2.
        if pixel_values.ndim == 5 and pixel_values.shape[2] == 3 and pixel_values.shape[1] != 3:
            pixel_values = pixel_values.permute(0, 2, 1, 3, 4)
        param = next(self._model.parameters(), None)
        if param is not None:
            pixel_values = pixel_values.to(device=self._device, dtype=param.dtype)
        with torch.no_grad():
            if self._pooling == "attention":
                # model(pixel_values) → clip_projector (native attention pool) → [1, 768].
                out = self._model(pixel_values)
            else:
                feats = self._model.extract_features(pixel_values)  # [1, 4096, 768]
                out = feats.mean(dim=1)  # [1, 768]
        vec = out.squeeze(0).float().tolist()
        return [float(x) for x in vec]

    async def encode(self, image: Any) -> list[float]:
        """A clip encoder has no per-frame encode; use :meth:`encode_clip`.

        (Spatial foveation is a per-frame path incompatible with a temporally
        native clip encoder — Topos rejects that combination at construction.)"""
        raise NotImplementedError(
            "InternVideoNextEncoder is a clip encoder (clip_len=16); call "
            "encode_clip(frames) with a full clip. Per-frame encode() is only "
            "meaningful for a clip_len=1 encoder such as DINOv2."
        )

    async def encode_clip(self, frames: Any) -> list[float]:
        """Encode a clip of ``clip_len`` frames to one pooled 768-dim vector."""
        if self._model is None:
            await self.load()
        import asyncio

        seq = list(frames)
        if len(seq) != self._clip_len:
            raise ValueError(
                f"encode_clip expects exactly clip_len={self._clip_len} frames, "
                f"got {len(seq)}"
            )
        pil = [_coerce_to_pil(f) for f in seq]
        return await asyncio.to_thread(self._forward_clip, pil)

    async def shutdown(self) -> None:
        self._model = None
        self._processor = None


def _load_videomae_processor() -> Any:
    """Load the VideoMAE image processor from the vendored preprocessor config.

    The processor config (``preprocessor_config.json``, size 224, ImageNet
    mean/std) is vendored alongside the modeling code, so this loads fully
    offline with no remote code (image processors carry no ``auto_map`` Python)."""
    from transformers import VideoMAEImageProcessor

    from kaine.modules.topos.internvideo_next_loader import vendored_code_dir

    return VideoMAEImageProcessor.from_pretrained(
        str(vendored_code_dir()), local_files_only=True
    )


def make_encoder(
    backend: str | None = None,
    *,
    model_id: str | None = None,
    device_preference: str | None = "auto",
    weights_dir: Any = None,
    clip_len: int = DEFAULT_CLIP_LEN,
    pooling: str = DEFAULT_POOLING,
    clip_resolution: int = DEFAULT_CLIP_RESOLUTION,
) -> Encoder:
    """Return the encoder for ``backend`` (config ``[topos].encoder_backend``).

    ``"internvideo_next"`` → :class:`InternVideoNextEncoder` (the shipped default,
    a temporally-native 768-dim clip encoder); ``"dinov2"`` → :class:`DINOv2Encoder`
    (a selectable Apache-2.0 per-frame fallback, ``clip_len = 1``). ``model_id=None``
    selects the per-backend default id. ``clip_len`` / ``pooling`` /
    ``clip_resolution`` configure the clip encoder and are ignored by DINOv2.
    Unknown backends raise ``ValueError``."""
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
            clip_len=clip_len,
            pooling=pooling,
            clip_resolution=clip_resolution,
        )
    raise ValueError(
        f"unknown encoder_backend {resolved!r}; expected one of {ENCODER_BACKENDS}"
    )


def _solid_image(width: int, height: int):
    """Tiny gray image used only to probe latent dim."""
    from PIL import Image

    return Image.new("RGB", (width, height), color=(128, 128, 128))
