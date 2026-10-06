# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-supervised acoustic encoders behind the ``ACOUSTIC_ENCODERS`` registry.

Dasheng-base (Apache-2.0) and WavJEPA-base (MIT) are vendored under
``external/dasheng/`` and ``external/wavjepa/``. Their weights are fetched once at
setup time (``kaine.setup.audio_ssl``) into deterministic local dirs. Runtime loads
those weights OFFLINE from the vendored modeling code, never using
``trust_remote_code`` or a hub call.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

from kaine.model_paths import models_dir
from kaine.modules.audition.acoustic import _decode_audio

_EMBEDDING_DIM = 768
_SAMPLE_RATE = 16000
_WEIGHTS_FILENAME = "model.safetensors"
_REVISION_FILENAME = "REVISION"

# (repository, pinned commit, weights directory name). The setup fetch reads
# this same table, and each pin must equal its external/<name>/UPSTREAM commit.
PINS: dict[str, tuple[str, str, str]] = {
    "dasheng": (
        "mispeech/dasheng-base",
        "d29a721c75b996ffa49e2a1f985349d191a4ae5e",
        "dasheng_base",
    ),
    "wavjepa": (
        "labhamlet/wavjepa-base",
        "6be4a5093f6c9adbbd55e00b6e5b8f067aa03345",
        "wavjepa_base",
    ),
}


def _vendored_external_root() -> Path:
    """Absolute path to the vendored ``external/`` package root."""
    return Path(__file__).resolve().parents[3] / "external"


def _ensure_repo_root_importable() -> None:
    """Make the top-level ``external`` package importable from any working
    directory: the vendored code is imported as ``external.<name>``, which
    resolves only when the repository root (the parent of ``external/``) is on
    ``sys.path``. It is appended, so it never shadows an installed package."""
    root = str(_vendored_external_root().parent)
    if root not in sys.path:
        sys.path.append(root)


class _SelfSupervisedAcousticEncoder:
    """Shared rolling-buffer + lazy-load plumbing for Dasheng and WavJEPA."""

    _kind: str

    def __init__(
        self,
        *,
        weights_dir: Path | None = None,
        device: str = "cpu",
        context_s: float = 2.0,
        model: Any | None = None,
        feature_extractor: Any | None = None,
    ) -> None:
        repo, revision, _ = PINS[self._kind]
        self.model_id = f"{repo}@{revision[:8]}"
        self._pinned_revision = revision
        self._weights_dir = weights_dir
        self._device = str(device)
        self._context_s = float(context_s)
        self._injected_model = model
        self._injected_feature_extractor = feature_extractor

        self._lock = threading.Lock()
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0

        self._model: Any | None = None
        self._feature_extractor: Any | None = None

    @property
    def embedding_dim(self) -> int:
        return _EMBEDDING_DIM

    def _default_weights_dir(self) -> Path:
        return models_dir() / PINS[self._kind][2]

    def _build(self, weights_path: Path) -> None:
        raise NotImplementedError

    def _forward(self, window: np.ndarray) -> Any:
        raise NotImplementedError

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return

            os.environ.setdefault("HF_HUB_OFFLINE", "1")

            if self._injected_model is not None:
                self._model = self._injected_model
                self._feature_extractor = self._injected_feature_extractor
                return

            weights_dir = (
                self._weights_dir
                if self._weights_dir is not None
                else self._default_weights_dir()
            )
            weights_path = weights_dir / _WEIGHTS_FILENAME

            if not weights_path.exists():
                raise FileNotFoundError(
                    f"{weights_path} missing; fetch with: "
                    f"python -m kaine.setup.audio_ssl {self._kind} --yes"
                )

            revision_path = weights_dir / _REVISION_FILENAME
            if revision_path.exists():
                recorded = revision_path.read_text().strip()
                if recorded != self._pinned_revision:
                    raise ValueError(
                        f"{revision_path} recorded revision {recorded!r} "
                        f"does not match pinned {self._pinned_revision!r}"
                    )

            self._build(weights_path)
            # Zero-persistence: once weights are loaded, do not keep the path.
            self._weights_dir = None

    def embed(self, audio_bytes: bytes, sample_rate: int) -> list[float]:
        self._load()

        chunk = _decode_audio(audio_bytes)
        if chunk.size > 0 and sample_rate != _SAMPLE_RATE:
            import torch
            import torchaudio.functional as TF

            waveform = torch.from_numpy(chunk)[None, :]
            waveform = TF.resample(waveform, sample_rate, _SAMPLE_RATE)
            chunk = waveform.squeeze(0).numpy().astype(np.float32)

        self._buffer.append(chunk)
        self._buffer_samples += chunk.size

        max_samples = int(self._context_s * _SAMPLE_RATE)
        while self._buffer_samples > max_samples and self._buffer:
            excess = self._buffer_samples - max_samples
            oldest = self._buffer[0]
            if oldest.size > excess:
                self._buffer[0] = oldest[excess:]
                self._buffer_samples -= excess
                break
            self._buffer.popleft()
            self._buffer_samples -= oldest.size

        if self._buffer_samples == 0:
            return [0.0] * _EMBEDDING_DIM

        if len(self._buffer) == 1:
            window = self._buffer[0]
        else:
            window = np.concatenate(list(self._buffer), dtype=np.float32)

        import torch

        with torch.inference_mode():
            hidden = self._forward(window)
            pooled = hidden.mean(dim=1)
            norm = torch.linalg.vector_norm(pooled, dim=1, keepdim=True)
            if norm.item() > 0:
                pooled = pooled / norm
            return pooled.squeeze(0).cpu().float().tolist()


class DashengAcousticEncoder(_SelfSupervisedAcousticEncoder):
    """Apache-2.0 Dasheng-base encoder (768-d, 16 kHz, 64 mel bins)."""

    _kind = "dasheng"

    def _build(self, weights_path: Path) -> None:
        import safetensors.torch

        _ensure_repo_root_importable()
        from external.dasheng.configuration_dasheng import DashengConfig
        from external.dasheng.feature_extraction_dasheng import DashengFeatureExtractor
        from external.dasheng.modeling_dasheng import DashengModel

        config_path = _vendored_external_root() / "dasheng" / "config.json"
        cfg = DashengConfig(**json.loads(config_path.read_text()))
        model = DashengModel(cfg)
        sd = safetensors.torch.load_file(weights_path)
        model.load_state_dict(sd, strict=True)
        model.eval()
        if self._device != "cpu":
            model = model.to(self._device)

        preprocessor_path = _vendored_external_root() / "dasheng" / "preprocessor_config.json"
        pp = json.loads(preprocessor_path.read_text())
        pp = {k: v for k, v in pp.items() if k not in ("auto_map", "feature_extractor_type")}
        feature_extractor = DashengFeatureExtractor(**pp)

        self._model = model
        self._feature_extractor = feature_extractor

    def _forward(self, window: np.ndarray) -> Any:

        feats = self._feature_extractor(
            window, sampling_rate=_SAMPLE_RATE, return_tensors="pt"
        )
        input_values = feats["input_values"]
        if self._device != "cpu":
            input_values = input_values.to(self._device)
        return self._model(input_values).hidden_states


class WavJEPAAcousticEncoder(_SelfSupervisedAcousticEncoder):
    """MIT WavJEPA-base encoder (768-d student context path, 16 kHz)."""

    _kind = "wavjepa"

    def _build(self, weights_path: Path) -> None:
        import safetensors.torch

        _ensure_repo_root_importable()
        from external.wavjepa.configuration_wavjepa import WavJEPAConfig
        from external.wavjepa.modeling_wavjepa import WavJEPAModel

        config_path = _vendored_external_root() / "wavjepa" / "config.json"
        cfg = WavJEPAConfig(**json.loads(config_path.read_text()))
        model = WavJEPAModel(cfg)
        sd = safetensors.torch.load_file(weights_path)
        model.load_state_dict(sd, strict=True)
        model.eval()
        if self._device != "cpu":
            model = model.to(self._device)

        # Runtime uses only the student (context) encoder path. The unused
        # submodules live on the inner WavJEPA module; dropping them frees
        # their weights.
        inner = model.model
        inner.teacher_encoder = None
        inner.decoder = None
        inner.decoder_to_encoder_mapper = None
        inner.encoder_to_decoder_mapper = None

        self._model = model

    def _forward(self, window: np.ndarray) -> Any:
        import torch

        x = torch.from_numpy(window)[None, None, :].to(torch.float32)
        if self._device != "cpu":
            x = x.to(self._device)
        out, _ts = self._model(x)
        return out
