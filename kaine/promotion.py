# SPDX-FileCopyrightText: 2024 KAINE Project
# SPDX-License-Identifier: MIT

"""Adapter promotion utilities.

Provides the :func:`promote` function which attempts to promote a candidate
adapter using a trainer. If the trainer indicates the adapter was refused, a
:class:`TrainerResultRefusedError` is raised.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

# Attempt to import the official TrainerResult enum; fall back to a minimal one.
try:
    from .trainer import TrainerResult  # type: ignore
except Exception:  # pragma: no cover
    class TrainerResult(Enum):
        """Fallback TrainerResult enumeration."""
        SUCCESS = "success"
        REFUSED = "refused"
        FAILURE = "failure"


class TrainerProtocol(Protocol):
    """Protocol that a trainer must implement."""
    def train(self, adapter: Any) -> Any:
        ...


class PromotionError(Exception):
    """Base class for promotion-related errors."""


class TrainerResultRefusedError(PromotionError):
    """Raised when the trainer refuses to promote the candidate adapter."""


def _execute_trainer(trainer: TrainerProtocol, adapter: Any) -> Any:
    """Execute the trainer with the given adapter.

    Supports ``train`` or ``run`` methods.
    """
    if hasattr(trainer, "train"):
        return trainer.train(adapter)  # type: ignore[arg-type]
    if hasattr(trainer, "run"):
        return trainer.run(adapter)  # type: ignore[arg-type]
    raise AttributeError(
        "Trainer object must implement a 'train' or 'run' method"
    )


def promote(candidate_adapter: Any, trainer: TrainerProtocol) -> None:
    """Promote a candidate adapter using the provided trainer.

    The trainer's ``train`` (or ``run``) method should return a
    :class:`TrainerResult`. If the result is :data:`TrainerResult.REFUSED` a
    :class:`TrainerResultRefusedError` is raised. If the result indicates
    success (:data:`TrainerResult.SUCCESS`) the function returns ``None``.
    Any other result causes a generic :class:`PromotionError`.

    The function also attempts to set a ``promoted`` attribute on the
    ``candidate_adapter`` if it exists.
    """
    result = _execute_trainer(trainer, candidate_adapter)

    # Directly handle the known enum type.
    if isinstance(result, TrainerResult):
        if result == TrainerResult.REFUSED:
            raise TrainerResultRefusedError(
                "Trainer refused to promote the adapter"
            )
        if result == TrainerResult.SUCCESS:
            if hasattr(candidate_adapter, "promoted"):
                setattr(candidate_adapter, "promoted", True)
            return None
        raise PromotionError(f"Unexpected trainer result: {result}")

    # Boolean truthiness handling.
    if isinstance(result, bool):
        if result:
            if hasattr(candidate_adapter, "promoted"):
                setattr(candidate_adapter, "promoted", True)
            return None
        raise PromotionError("Trainer reported failure")

    # String handling – accept common literals.
    if isinstance(result, str):
        normalized = result.strip().upper()
        if normalized == "SUCCESS":
            if hasattr(candidate_adapter, "promoted"):
                setattr(candidate_adapter, "promoted", True)
            return None
        if normalized == "REFUSED":
            raise TrainerResultRefusedError(
                "Trainer refused to promote the adapter"
            )
        raise PromotionError(f"Trainer returned unknown result string: {result}")

    # If we cannot interpret the result, raise a generic error.
    raise PromotionError(
        f"Unable to interpret trainer result: {result!r}"
    )


__all__ = [
    "TrainerResultRefusedError",
    "PromotionError",
    "promote",
    "TrainerResult",
]