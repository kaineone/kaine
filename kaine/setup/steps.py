# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Declarative step model shared by the terminal wizard and, later, the browser setup."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, eq=False)
class Field:
    name: str
    prompt: str
    kind: str  # "bool", "int", "text", "choice", "multichoice"
    default: Any
    choices: tuple[str, ...] = ()
    validate: Callable[[Any], str | None] | None = None

    def __post_init__(self) -> None:
        allowed = {"bool", "int", "text", "choice", "multichoice"}
        if self.kind not in allowed:
            raise ValueError(f"unsupported field kind: {self.kind}")


@dataclass(eq=False)
class StepContext:
    config: dict[str, Any]
    host: dict[str, Any]
    extra: dict[str, Any]


@dataclass(frozen=True, eq=False)
class Step:
    id: str
    title: str
    explanation: Callable[[StepContext], list[str]]
    fields: Callable[[StepContext], tuple[Field, ...]]
    applies: Callable[[StepContext], bool]
    apply: Callable[[StepContext, dict[str, Any]], None]


# Every module the wizard can enable or disable, in canonical order, plus echo.
_SETUP_MODULES = (
    "soma",
    "chronos",
    "thymos",
    "eidolon",
    "mnemos",
    "nous",
    "lingua",
    "hypnos",
    "topos",
    "praxis",
    "audition",
    "vox",
    "empatheia",
    "phantasia",
    "perception",
    "mundus",
    "echo",
)

OWNED_KEYS: frozenset[str] = frozenset(
    {
        # hardware steps
        "hardware.allowed_devices",
        "hardware.cpu_threads",
        "hardware.devices.organ",
        "hardware.devices.vision",
        "hypnos.voice_alignment.training_device",
        "phantasia.training_device",
        "topos.device",
        "embedding.device",
        "audition.emotion_device",
        "services.model_server.shared",
        "services.chatterbox.shared",
        "services.speaches.shared",
        "storage.data_root",
        # deployment tier
        "deployment.tier",
        # modules
        *(f"modules.{m}" for m in _SETUP_MODULES),
        # model / voice / STT
        "lingua.model_id",
        "vox.predefined_voice_id",
        "audition.stt_model",
        # voice-alignment trainer provisioning
        "hypnos.voice_alignment.trainer_python",
        "hypnos.voice_alignment.trainer_backend",
        # CL1 substrate plugin
        "plugins.enabled",
        "plugins.cl1.substrate.target",
        "plugins.cl1.substrate.accelerated_time",
        "plugins.cl1.substrate.data_source",
        *(f"plugins.cl1.substrate.territories.{m}" for m in _SETUP_MODULES),
        *(f"plugins.cl1.backends.{m}" for m in _SETUP_MODULES),
        # research metrics
        "research_submission.enabled",
        "research_submission.tier",
        "research_submission.recipient",
        "transfer.recipient",
        # state encryption
        "security.state_encryption.enabled",
    }
)

_MISSING = object()


def assert_owned(changed: set[str]) -> None:
    """Raise ``ValueError`` if any changed key is outside the owned-key allowlist."""
    offenders = changed - OWNED_KEYS
    if offenders:
        raise ValueError(
            f"step wrote config key(s) outside the owned set: {sorted(offenders)}"
        )


def _flatten(cfg: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in cfg.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, dotted))
        else:
            out[dotted] = value
    return out


def owned_changes(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    """Return the dotted config keys that changed between ``before`` and ``after``."""
    flat_before = _flatten(before)
    flat_after = _flatten(after)
    keys = set(flat_before) | set(flat_after)
    return {
        k
        for k in keys
        if flat_before.get(k, _MISSING) != flat_after.get(k, _MISSING)
    }


def parse_answer(field: Field, raw: str) -> tuple[Any, str | None]:
    """Parse ``raw`` into the Python value expected by ``field``.

    Returns ``(value, error_message)``.  ``error_message`` is ``None`` on
    success.
    """
    raw = (raw or "").strip()
    if not raw:
        value = field.default
        if field.validate is not None:
            err = field.validate(value)
            if err:
                return value, err
        return value, None

    value: Any = None
    error: str | None = None

    if field.kind == "bool":
        low = raw.lower()
        if low in {"y", "yes", "true"}:
            value = True
        elif low in {"n", "no", "false"}:
            value = False
        else:
            error = "answer yes or no"
    elif field.kind == "int":
        try:
            value = int(raw)
        except ValueError:
            error = "must be an integer"
    elif field.kind == "choice":
        if raw in field.choices:
            value = raw
        else:
            error = f"must be one of: {', '.join(field.choices)}"
    elif field.kind == "multichoice":
        parts = [p.strip() for p in raw.split(",") if p.strip() != ""]
        if not parts:
            error = "at least one choice is required"
        else:
            invalid = [p for p in parts if p not in field.choices]
            if invalid:
                error = (
                    f"invalid choices: {', '.join(invalid)}; "
                    f"must be one of: {', '.join(field.choices)}"
                )
            else:
                seen: set[str] = set()
                value = []
                for part in parts:
                    if part not in seen:
                        seen.add(part)
                        value.append(part)
    elif field.kind == "text":
        value = raw
    else:  # pragma: no cover - guarded by __post_init__
        error = f"unknown field kind: {field.kind}"

    if error is not None:
        return None, error

    if field.validate is not None:
        err = field.validate(value)
        if err:
            return value, err

    return value, None


def _show_default(default: Any) -> str:
    if isinstance(default, bool):
        return "Y/n" if default else "y/N"
    if isinstance(default, (list, tuple)):
        return ", ".join(str(x) for x in default)
    return str(default)


def run_step(
    step: Step,
    ctx: StepContext,
    *,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    defaults: bool,
) -> dict[str, Any]:
    """Execute a single step and return the collected answers."""
    if not step.applies(ctx):
        return {}

    out("-" * 70 + "\n")
    out(step.title + "\n")
    for line in step.explanation(ctx):
        out(line + "\n")

    answers: dict[str, Any] = {}
    for field in step.fields(ctx):
        if defaults:
            answers[field.name] = field.default
            continue

        shown = _show_default(field.default)
        prompt = f"{field.prompt} [{shown}]: "
        attempts = 0
        value: Any = field.default
        while True:
            parsed, err = parse_answer(field, input_fn(prompt))
            if err is None:
                value = parsed
                break
            attempts += 1
            out(f"  {err}\n")
            if attempts >= 3:
                out(f"  using the default: {shown}\n")
                break
        answers[field.name] = value

    step.apply(ctx, answers)
    return answers
