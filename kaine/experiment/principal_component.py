# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The direction and mean of the positive control's projection.

Paper Appendix A.8: v_j, the first principal component of processor j's inputs, is the
unit direction along which they vary most (Jolliffe 2002), and mu_j is their mean. Both
are estimated from a preliminary run of the on arm. The preliminary run accumulates the
inputs' mean and covariance in memory and writes only these summaries; no input is stored.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PC_SCHEMA = "kaine.positive_control.principal_component"
PC_SCHEMA_VERSION = 1
PC_ROOT = Path("data/evaluation/positive_control")


class PrincipalComponentError(ValueError):
    """Invalid principal-component data or estimator state."""


@dataclass(frozen=True)
class PrincipalComponent:
    """A first principal component summary written by a preliminary run."""

    processor: str
    run_id: str
    n_inputs: int
    dim: int
    mean: tuple[float, ...]
    direction: tuple[float, ...]
    variance: float  # largest eigenvalue of the sample covariance (divisor n - 1)
    total_variance: float  # trace of the sample covariance

    def project(self, x: Sequence[float]) -> float:
        """Return direction . (x - mean).

        Raises:
            PrincipalComponentError: if len(x) is not dim.
        """
        if len(x) != self.dim:
            raise PrincipalComponentError(
                f"project: expected a vector of length {self.dim}, got {len(x)}"
            )
        return sum(d * (xi - m) for d, xi, m in zip(self.direction, x, self.mean))

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable payload for this summary."""
        return {
            "schema": PC_SCHEMA,
            "schema_version": PC_SCHEMA_VERSION,
            "processor": self.processor,
            "run_id": self.run_id,
            "n_inputs": self.n_inputs,
            "dim": self.dim,
            "mean": list(self.mean),
            "direction": list(self.direction),
            "variance": self.variance,
            "total_variance": self.total_variance,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> PrincipalComponent:
        """Validate a payload and return a PrincipalComponent.

        Raises:
            PrincipalComponentError: if the schema or version do not match, if
                processor or run_id are empty, if n_inputs or dim are invalid, if
                mean or direction are not finite vectors of length dim, if the
                direction is not unit length, or if variance or total_variance are
                invalid.
        """
        def _require(condition: bool, message: str) -> None:
            if not condition:
                raise PrincipalComponentError(message)

        _require(payload.get("schema") == PC_SCHEMA, f"schema mismatch: expected {PC_SCHEMA!r}")
        _require(
            payload.get("schema_version") == PC_SCHEMA_VERSION,
            f"schema_version mismatch: expected {PC_SCHEMA_VERSION!r}",
        )
        processor = payload.get("processor")
        _require(isinstance(processor, str) and processor, "processor must be a non-empty string")
        run_id = payload.get("run_id")
        _require(isinstance(run_id, str) and run_id, "run_id must be a non-empty string")
        n_inputs = payload.get("n_inputs")
        _require(
            isinstance(n_inputs, int) and not isinstance(n_inputs, bool) and n_inputs >= 2,
            "n_inputs must be an int >= 2",
        )
        dim = payload.get("dim")
        _require(
            isinstance(dim, int) and not isinstance(dim, bool) and dim >= 1,
            "dim must be an int >= 1",
        )
        mean = payload.get("mean")
        _require(
            isinstance(mean, list) and len(mean) == dim,
            f"mean must be a list of length {dim}",
        )
        _require(
            all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in mean),
            "mean values must be finite numbers",
        )
        direction = payload.get("direction")
        _require(
            isinstance(direction, list) and len(direction) == dim,
            f"direction must be a list of length {dim}",
        )
        _require(
            all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in direction),
            "direction values must be finite numbers",
        )
        norm = math.sqrt(sum(x * x for x in direction))
        _require(norm > 0.0, "direction must not be the zero vector")
        _require(abs(norm - 1.0) <= 1e-6, f"direction must be a unit vector, norm was {norm}")
        variance = payload.get("variance")
        _require(
            isinstance(variance, (int, float))
            and not isinstance(variance, bool)
            and math.isfinite(variance)
            and variance > 0.0,
            "variance must be a finite positive number",
        )
        total_variance = payload.get("total_variance")
        _require(
            isinstance(total_variance, (int, float))
            and not isinstance(total_variance, bool)
            and math.isfinite(total_variance),
            "total_variance must be a finite number",
        )
        _require(
            total_variance >= variance * (1.0 - 1e-9),
            "total_variance must be at least variance",
        )
        return cls(
            processor=processor,
            run_id=run_id,
            n_inputs=n_inputs,
            dim=dim,
            mean=tuple(float(x) for x in mean),
            direction=tuple(float(x) for x in direction),
            variance=float(variance),
            total_variance=float(total_variance),
        )


class PrincipalComponentEstimator:
    """Online estimator for the first principal component and mean.

    Accumulates the sample mean and the co-moment matrix with Welford's update, so the
    sample covariance is numerically stable.
    """

    def __init__(self) -> None:
        self._n = 0
        self._dim: int | None = None
        self._mean: np.ndarray | None = None
        self._m2: np.ndarray | None = None

    @property
    def n(self) -> int:
        """Number of input vectors added so far."""
        return self._n

    def add(self, x: Sequence[float]) -> None:
        """Add one input vector to the running estimate.

        The first call fixes the dimension. A later vector of another length, a
        non-finite value, or a vector that is not one-dimensional raises
        PrincipalComponentError.

        Args:
            x: one input vector.
        """
        arr = np.asarray(x, dtype=np.float64)
        if arr.ndim != 1:
            raise PrincipalComponentError("add: input must be one-dimensional")
        if arr.shape[0] == 0:
            raise PrincipalComponentError("add: input vector must not be empty")
        if not np.all(np.isfinite(arr)):
            raise PrincipalComponentError("add: input contains a non-finite value")
        if self._n == 0:
            self._dim = arr.shape[0]
            self._mean = np.zeros(self._dim, dtype=np.float64)
            self._m2 = np.zeros((self._dim, self._dim), dtype=np.float64)
        elif arr.shape[0] != self._dim:
            raise PrincipalComponentError(
                f"add: expected dimension {self._dim}, got {arr.shape[0]}"
            )
        self._n += 1
        n = self._n
        delta = arr - self._mean
        self._mean += delta / n
        delta2 = arr - self._mean
        self._m2 += np.outer(delta, delta2)

    def result(self, *, processor: str, run_id: str) -> PrincipalComponent:
        """Return the PrincipalComponent estimated from the added vectors.

        Forms the sample covariance M2 / (n - 1), takes numpy.linalg.eigh, and uses the
        eigenvector of the largest eigenvalue as the direction. The sign is fixed so
        that the entry with the largest absolute value is positive.

        Raises:
            PrincipalComponentError: if fewer than 2 vectors have been added, if
                processor or run_id are empty, or if the largest eigenvalue is not
                positive (constant inputs).
        """
        if self._n < 2:
            raise PrincipalComponentError(f"result: need at least 2 inputs, got {self._n}")
        if not isinstance(processor, str) or not processor:
            raise PrincipalComponentError("result: processor must be a non-empty string")
        if not isinstance(run_id, str) or not run_id:
            raise PrincipalComponentError("result: run_id must be a non-empty string")
        n = self._n
        cov = self._m2 / (n - 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        idx = int(np.argmax(eigvals))
        variance = float(eigvals[idx])
        if variance <= 0.0:
            raise PrincipalComponentError(
                "result: largest eigenvalue is not positive; inputs are constant"
            )
        direction = eigvecs[:, idx].copy()
        norm = float(np.linalg.norm(direction))
        if norm == 0.0:
            raise PrincipalComponentError("result: computed direction has zero norm")
        direction /= norm
        max_idx = int(np.argmax(np.abs(direction)))
        if direction[max_idx] < 0.0:
            direction = -direction
        total_variance = float(np.trace(cov))
        return PrincipalComponent(
            processor=processor,
            run_id=run_id,
            n_inputs=n,
            dim=self._dim,
            mean=tuple(float(v) for v in self._mean),
            direction=tuple(float(v) for v in direction),
            variance=variance,
            total_variance=total_variance,
        )


def principal_component_path(root: Path, run_id: str, processor: str) -> Path:
    """Return the storage path root / run_id / principal_component_{processor}.json.

    Raises:
        PrincipalComponentError: if run_id or processor contain '/' or '\\', or are
            empty, '.', or '..'.
    """
    def _check(part: str, name: str) -> None:
        if not isinstance(part, str):
            raise PrincipalComponentError(f"{name} must be a string")
        if part in ("", ".", ".."):
            raise PrincipalComponentError(f"{name} must not be empty, '.' or '..'")
        if "/" in part or "\\" in part:
            raise PrincipalComponentError(f"{name} must not contain '/' or '\\'")

    _check(run_id, "run_id")
    _check(processor, "processor")
    return root / run_id / f"principal_component_{processor}.json"


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 bytes for a JSON payload."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    """Return the hex sha256 of the file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_principal_component(pc: PrincipalComponent, path: Path) -> str:
    """Write pc.to_payload() atomically and return the sha256 of the written bytes.

    The parent directories are created, the data is written to a sibling ``.tmp`` file,
    and then moved into place with os.replace.
    """
    data = canonical_bytes(pc.to_payload())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return file_sha256(path)


def load_principal_component(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> PrincipalComponent:
    """Read and validate a PrincipalComponent from a JSON file.

    Raises:
        PrincipalComponentError: if the file is missing, the JSON is invalid, the
            sha256 does not match (when given), or the payload fails validation.
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise PrincipalComponentError(f"load: file not found: {path}") from None
    if expected_sha256 is not None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise PrincipalComponentError(f"load: sha256 mismatch for {path}")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PrincipalComponentError(f"load: invalid JSON in {path}: {exc}") from None
    return PrincipalComponent.from_payload(payload)


__all__ = [
    "PC_ROOT",
    "PC_SCHEMA",
    "PC_SCHEMA_VERSION",
    "PrincipalComponent",
    "PrincipalComponentError",
    "PrincipalComponentEstimator",
    "canonical_bytes",
    "file_sha256",
    "load_principal_component",
    "principal_component_path",
    "write_principal_component",
]
