# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import itertools
import logging
import math
from typing import Any

import numpy as np

_log = logging.getLogger(__name__)


class ContentEncoder:
    """Linear encoder mapping processor latent to shared code space."""

    def __init__(self, input_dim: int, code_dim: int, *, lr: float = 1e-3):
        if input_dim <= 0:
            raise ValueError("input_dim must be positive")
        if code_dim <= 0:
            raise ValueError("code_dim must be positive")
        if lr <= 0.0:
            raise ValueError("lr must be positive")
        self._input_dim = int(input_dim)
        self._code_dim = int(code_dim)
        self._lr = float(lr)
        # Xavier normal init — zero weights would be a fixed point since
        # z_k = tanh(0) = 0 makes the decoder outer-product gradient zero.
        scale = math.sqrt(2.0 / (self._input_dim + self._code_dim))
        rng = np.random.default_rng(input_dim * 31 + code_dim)
        self._weights = rng.normal(0.0, scale, (self._code_dim, self._input_dim)).astype(
            np.float64
        )

    def encode(self, latent: np.ndarray) -> np.ndarray:
        x = np.asarray(latent, dtype=np.float64)
        return np.tanh(self._weights @ x)

    def adapt(self, x_input: np.ndarray, grad_from_decoder: np.ndarray) -> None:
        x = np.asarray(x_input, dtype=np.float64)
        grad = np.asarray(grad_from_decoder, dtype=np.float64)
        z = np.tanh(self._weights @ x)
        dz = grad * (1.0 - z ** 2)
        grad_W = np.outer(dz, x)
        if not np.all(np.isfinite(grad_W)):
            return
        self._weights -= self._lr * grad_W

    def state_dict(self) -> dict[str, Any]:
        return {
            "weights": self._weights.tolist(),
            "input_dim": self._input_dim,
            "code_dim": self._code_dim,
            "lr": self._lr,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        weights = np.asarray(state["weights"], dtype=np.float64)
        if weights.shape != (self._code_dim, self._input_dim):
            raise ValueError(
                f"ContentEncoder state shape mismatch: expected "
                f"({self._code_dim}, {self._input_dim}), got {weights.shape}"
            )
        if not np.all(np.isfinite(weights)):
            raise ValueError("ContentEncoder state contains non-finite weights")
        self._weights = weights
        saved_lr = state.get("lr")
        if saved_lr is not None and saved_lr != self._lr:
            import logging

            logging.getLogger(__name__).info(
                "ContentEncoder: snapshot lr=%s differs from construction lr=%s",
                saved_lr,
                self._lr,
            )


class ContentDecoder:
    """Linear decoder mapping shared code back to processor latent space."""

    def __init__(self, code_dim: int, output_dim: int, *, lr: float = 1e-3):
        if code_dim <= 0:
            raise ValueError("code_dim must be positive")
        if output_dim <= 0:
            raise ValueError("output_dim must be positive")
        if lr <= 0.0:
            raise ValueError("lr must be positive")
        self._code_dim = int(code_dim)
        self._output_dim = int(output_dim)
        self._lr = float(lr)
        scale = math.sqrt(2.0 / (self._code_dim + self._output_dim))
        rng = np.random.default_rng(code_dim * 31 + output_dim)
        self._weights = rng.normal(0.0, scale, (self._output_dim, self._code_dim)).astype(
            np.float64
        )

    def decode(self, z_k: np.ndarray) -> np.ndarray:
        z = np.asarray(z_k, dtype=np.float64)
        return np.tanh(self._weights @ z)

    def adapt(self, z_k: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray]:
        z = np.asarray(z_k, dtype=np.float64)
        t = np.asarray(target, dtype=np.float64).reshape(self._output_dim)

        y = np.tanh(self._weights @ z)
        err = y - t
        loss = float(np.mean(err * err))

        dL_dy = err * (2.0 / self._output_dim)
        dtanh = 1.0 - y ** 2
        dL_dlinear = dL_dy * dtanh

        grad_W = np.outer(dL_dlinear, z)

        if not math.isfinite(loss) or not np.all(np.isfinite(grad_W)):
            return 0.0, np.zeros(self._code_dim, dtype=np.float64)

        grad_input = self._weights.T @ dL_dlinear
        self._weights -= self._lr * grad_W

        return loss, grad_input

    def state_dict(self) -> dict[str, Any]:
        return {
            "weights": self._weights.tolist(),
            "code_dim": self._code_dim,
            "output_dim": self._output_dim,
            "lr": self._lr,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        weights = np.asarray(state["weights"], dtype=np.float64)
        if weights.shape != (self._output_dim, self._code_dim):
            raise ValueError(
                f"ContentDecoder state shape mismatch: expected "
                f"({self._output_dim}, {self._code_dim}), got {weights.shape}"
            )
        if not np.all(np.isfinite(weights)):
            raise ValueError("ContentDecoder state contains non-finite weights")
        self._weights = weights
        saved_lr = state.get("lr")
        if saved_lr is not None and saved_lr != self._lr:
            import logging

            logging.getLogger(__name__).info(
                "ContentDecoder: snapshot lr=%s differs from construction lr=%s",
                saved_lr,
                self._lr,
            )


class ContentLevel:
    """Content-bearing second level of the workspace."""

    def __init__(
        self,
        processor_dims: dict[str, int],
        code_dim: int = 32,
        *,
        encoder_lr: float = 1e-3,
        decoder_lr: float = 1e-3,
    ):
        if code_dim <= 0:
            raise ValueError("code_dim must be positive")
        self._code_dim = int(code_dim)
        self._encoders: dict[str, ContentEncoder] = {}
        self._decoders: dict[str, ContentDecoder] = {}
        for name, dim in processor_dims.items():
            self._encoders[name] = ContentEncoder(dim, self._code_dim, lr=encoder_lr)
            self._decoders[name] = ContentDecoder(self._code_dim, dim, lr=decoder_lr)
        self._z_k: np.ndarray | None = None
        self._last_latents: dict[str, np.ndarray] = {}

    def update_code(
        self, latents: dict[str, np.ndarray], intensities: dict[str, float]
    ) -> np.ndarray:
        numerator = np.zeros(self._code_dim, dtype=np.float64)
        denominator = 0.0
        self._last_latents.clear()

        for name in intensities:
            if name not in latents or name not in self._encoders:
                continue
            intensity = float(intensities[name])
            if intensity == 0.0:
                continue
            latent = np.asarray(latents[name], dtype=np.float64)
            self._last_latents[name] = latent.copy()
            encoded = self._encoders[name].encode(latent)
            numerator += intensity * encoded
            denominator += intensity

        if denominator == 0.0:
            if self._z_k is not None:
                return self._z_k.copy()
            self._z_k = np.zeros(self._code_dim, dtype=np.float64)
            return self._z_k.copy()

        self._z_k = numerator / denominator
        return self._z_k.copy()

    def predict(self, processor: str) -> list[float] | None:
        if self._z_k is None or processor not in self._decoders:
            return None
        return self._decoders[processor].decode(self._z_k).tolist()

    def train_step(self, observed: dict[str, np.ndarray]) -> dict[str, float]:
        losses: dict[str, float] = {}
        if self._z_k is None:
            return losses
        for name, target in observed.items():
            if name not in self._decoders or name not in self._encoders:
                continue
            loss, grad_z = self._decoders[name].adapt(self._z_k, target)
            latent = self._last_latents.get(name)
            if latent is not None:
                self._encoders[name].adapt(latent, grad_z)
            losses[name] = loss
        return losses

    def train_step_translation(self, observed: dict[str, np.ndarray]) -> dict[str, float]:
        """Cycle-consistency training across processor pairs."""
        losses: dict[str, float] = {}
        names = [n for n in observed if n in self._encoders and n in self._decoders]
        for p, q in itertools.combinations(names, 2):
            lat_p = np.asarray(observed[p], dtype=np.float64)
            lat_q = np.asarray(observed[q], dtype=np.float64)
            z_pq = self._encoders[q].encode(lat_q)
            loss_pq, grad_pq = self._decoders[p].adapt(z_pq, lat_p)
            self._encoders[q].adapt(lat_q, grad_pq)
            z_qp = self._encoders[p].encode(lat_p)
            loss_qp, grad_qp = self._decoders[q].adapt(z_qp, lat_q)
            self._encoders[p].adapt(lat_p, grad_qp)
            losses[p] = losses.get(p, 0.0) + loss_pq
            losses[q] = losses.get(q, 0.0) + loss_qp
        return losses

    @property
    def code(self) -> np.ndarray | None:
        return None if self._z_k is None else self._z_k.copy()

    @property
    def code_dim(self) -> int:
        return self._code_dim

    @property
    def enabled(self) -> bool:
        return True

    def state_dict(self) -> dict[str, Any]:
        return {
            "encoders": {n: e.state_dict() for n, e in self._encoders.items()},
            "decoders": {n: d.state_dict() for n, d in self._decoders.items()},
            "z_k": None if self._z_k is None else self._z_k.tolist(),
            "code_dim": self._code_dim,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if "code_dim" in state and int(state["code_dim"]) != self._code_dim:
            raise ValueError(
                f"ContentLevel code_dim mismatch: expected "
                f"{self._code_dim}, got {state['code_dim']}"
            )
        saved_enc = state.get("encoders", {})
        dropped_enc = set(saved_enc) - set(self._encoders)
        if dropped_enc:
            _log.warning("ContentLevel: dropping saved encoder weights for %s", dropped_enc)
        for name, s in saved_enc.items():
            if name in self._encoders:
                self._encoders[name].load_state_dict(s)
        saved_dec = state.get("decoders", {})
        dropped_dec = set(saved_dec) - set(self._decoders)
        if dropped_dec:
            _log.warning("ContentLevel: dropping saved decoder weights for %s", dropped_dec)
        for name, s in saved_dec.items():
            if name in self._decoders:
                self._decoders[name].load_state_dict(s)
        z_data = state.get("z_k")
        if z_data is None:
            self._z_k = None
        else:
            z_arr = np.asarray(z_data, dtype=np.float64)
            if z_arr.shape != (self._code_dim,):
                raise ValueError(
                    f"ContentLevel z_k shape mismatch: expected "
                    f"({self._code_dim},), got {z_arr.shape}"
                )
            if not np.all(np.isfinite(z_arr)):
                raise ValueError("ContentLevel z_k contains non-finite values")
            self._z_k = z_arr.copy()
