# SPDX-FileCopyrightText: 2023-2026 KAINE
# SPDX-License-Identifier: MIT
"""Utilities for invoking a training subprocess within the Sleep module.

This module defines the public API for subprocess‑based voice model training,
including result handling, validation, and auditing helpers.  It also
introduces a new ``TrainerResultRefusedError`` exception that is raised when a
trainer result indicates a refusal (self‑denial ablation) gate.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

# Ensure ``__all__`` exists so that we can extend it without overwriting any
# existing definition from the original module.
if '__all__' not in globals():
    __all__ = []  # type: ignore[var-annotated]

# ---------------------------------------------------------------------------
# TrainerResult
# ---------------------------------------------------------------------------
# Define ``TrainerResult`` only if the original module did not already provide it.
if 'TrainerResult' not in globals():
    class TrainerResult:
        """Container for trainer result data.

        Attributes are dynamically set from provided keyword arguments.
        The ``success`` attribute is always present and cast to ``bool``.
        """

        def __init__(self, **kwargs: Any):
            for key, value in kwargs.items():
                setattr(self, key, value)
            # Guarantee the ``success`` flag exists and is a ``bool``.
            self.success = bool(getattr(self, "success", False))

    __all__.append("TrainerResult")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# New refusal‑gate exception
# ---------------------------------------------------------------------------
if 'TrainerResultRefusedError' not in globals():
    class TrainerResultRefusedError(RuntimeError):
        """Exception indicating a trainer result was refused (self‑denial ablation)."""
        pass

    __all__.append("TrainerResultRefusedError")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Validation helper (refusal-gate aware)
# ---------------------------------------------------------------------------
def validate_trainer_result(result: Any) -> None:
    """Validate a trainer result, handling the new refusal gate.

    Parameters
    ----------
    result
        The trainer result object to validate.

    Raises
    ------
    TrainerResultRefusedError
        If the result indicates a refusal.
    ValueError
        If the result indicates failure.
    """
    refusal = getattr(result, "refusal", None) or getattr(result, "refused", None)
    if refusal:
        raise TrainerResultRefusedError(refusal)
    if not getattr(result, "success", False):
        raise ValueError(
            f"Trainer result indicates failure: {getattr(result, 'reason', 'unknown')}"
        )


__all__.append("validate_trainer_result")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Auditing helper (refusal-aware)
# ---------------------------------------------------------------------------
def audit_abliteration_from_result(result: Any) -> Mapping[str, Any]:
    """Create an audit mapping from a trainer result, propagating refusals."""
    audit: dict = {}
    for attr in dir(result):
        if attr.startswith("_"):
            continue
        try:
            value = getattr(result, attr)
        except Exception:
            continue
        if callable(value):
            continue
        audit[attr] = value
    refusal = getattr(result, "refusal", None) or getattr(result, "refused", None)
    if refusal:
        audit["refusal"] = refusal
    return audit


__all__.append("audit_abliteration_from_result")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Subprocess trainer implementation
# ---------------------------------------------------------------------------
# Define ``SubprocessVoiceTrainer`` only if it does not already exist.
if 'SubprocessVoiceTrainer' not in globals():
    class SubprocessVoiceTrainer:
        """Run a training script as a subprocess and return a :class:`TrainerResult`.

        Parameters
        ----------
        command : Union[str, Sequence[str]]
            Command to execute – can be a script path (as ``str``) or a complete
            command list.
        cwd : Optional[Path], optional
            Working directory for the subprocess.
        env : Optional[Mapping[str, str]], optional
            Environment variables for the subprocess.
        timeout : Optional[int], optional
            Timeout for the subprocess in seconds.
        **kwargs
            Additional keyword arguments are stored for compatibility but not used.
        """

        def __init__(
            self,
            command: Union[str, Sequence[str]],
            cwd: Optional[Path] = None,
            env: Optional[Mapping[str, str]] = None,
            timeout: Optional[int] = None,
            **kwargs: Any,
        ) -> None:
            self.command = command if isinstance(command, (list, tuple)) else [command]
            self.cwd = cwd
            self.env = env
            self.timeout = timeout
            self._extra_kwargs = kwargs  # retained for forwards‑compatibility

        def run(self) -> TrainerResult:
            """Execute the subprocess, parse its JSON output, and build a ``TrainerResult``.

            The subprocess is expected to emit a JSON document on stdout.  Any
            parsing error is treated as a failure result.
            """
            # Resolve the command into a list of string arguments.
            cmd = [str(part) for part in self.command]

            proc = subprocess.run(
                cmd,
                cwd=self.cwd,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            # Attempt to decode stdout as JSON.
            try:
                stdout_str = proc.stdout.strip()
                data = json.loads(stdout_str) if stdout_str else {}
            except Exception as exc:
                data = {
                    "success": False,
                    "error": f"Failed to parse trainer output as JSON: {exc}",
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }

            # Normalise the success flag.
            success = bool(data.get("success", False))
            # Propagate any refusal indicator if present.
            refusal = data.get("refusal") or data.get("refused")
            # Build the result object.
            result = TrainerResult(**data)
            result.success = success
            if refusal:
                setattr(result, "refusal", refusal)
            return result

        # Backwards‑compatibility alias.
        def train(self) -> TrainerResult:
            """Alias for ``run`` – retained for legacy callers."""
            return self.run()

    __all__.append("SubprocessVoiceTrainer")  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Compatibility aliases for the original class name
# ---------------------------------------------------------------------------
# Ensure both ``SubprocessTrainer`` and ``SubprocessVoiceTrainer`` refer to the same
# concrete implementation, regardless of which name the original code used.
if 'SubprocessTrainer' in globals() and 'SubprocessVoiceTrainer' not in globals():
    SubprocessVoiceTrainer = SubprocessTrainer  # type: ignore[name-defined]  # noqa: F821
    __all__.append("SubprocessVoiceTrainer")  # type: ignore[assignment]
elif 'SubprocessVoiceTrainer' in globals() and 'SubprocessTrainer' not in globals():
    SubprocessTrainer = SubprocessVoiceTrainer  # type: ignore[name-defined]  # noqa: F821
    __all__.append("SubprocessTrainer")  # type: ignore[assignment]
else:
    # Neither name was defined – create a default alias pair.
    if 'SubprocessVoiceTrainer' in globals():
        SubprocessTrainer = SubprocessVoiceTrainer  # type: ignore[name-defined]  # noqa: F821
        __all__.append("SubprocessTrainer")  # type: ignore[assignment]
    elif 'SubprocessTrainer' in globals():
        SubprocessVoiceTrainer = SubprocessTrainer  # type: ignore[name-defined]  # noqa: F821
        __all__.append("SubprocessVoiceTrainer")  # type: ignore[assignment]
