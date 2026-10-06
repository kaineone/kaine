# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Declarative steps for the first-run wizard.

Each factory returns a :class:`kaine.setup.steps.Step` describing one wizard
choice.  The terminal driver and, later, the browser driver will both render
these same steps.
"""
from __future__ import annotations

from typing import Any, Callable

from kaine.setup import wizard_core as _wizard
from kaine.setup.steps import Field, Step, StepContext


def _existing(cfg: dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Return the value at ``dotted`` in ``cfg`` if it exists, else ``default``."""
    if not cfg:
        return default
    parts = dotted.split(".")
    cur = cfg
    for p in parts[:-1]:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    if not isinstance(cur, dict):
        return default
    return cur.get(parts[-1], default)


def _module_preset_default(ctx: StepContext, recommended: str) -> str:
    """Prefer the existing module set as a preset letter, else ``recommended``."""

    existing = ctx.extra.get("existing_config") or {}
    mods = existing.get("modules")
    if not isinstance(mods, dict):
        return recommended
    base = _wizard.base_thesis_modules()
    full = _wizard.FULL_ENTITY_MODULES.copy()
    if all(mods.get(m) == base.get(m) for m in _wizard.MODULE_ORDER) and mods.get("echo") is False:
        return "b"
    if all(mods.get(m) == full.get(m) for m in _wizard.MODULE_ORDER) and mods.get("echo") is False:
        return "f"
    return "c"


def _make_line(ctx: StepContext) -> Callable[[str], None]:
    out = ctx.extra["out"]

    def line(text: str = "") -> None:
        out(text + "\n")

    return line


# -----------------------------------------------------------------------------
# Orientation
# -----------------------------------------------------------------------------


def orientation_step() -> Step:
    def explanation(_ctx: StepContext) -> list[str]:
        return [
            "This wizard records your local choices to config/kaine.operator.toml",
            "(gitignored). It NEVER edits the shipped config/kaine.toml and NEVER",
            "boots the entity. It will set up: license acknowledgement, device",
            "assignments from a hardware scan, which modules to enable, the served",
            "model/voice/STT ids, optional dependency extras, opt-in research",
            "metrics, and state encryption.",
        ]

    return Step(
        id="orientation",
        title="KAINE first-run setup",
        explanation=explanation,
        fields=lambda _ctx: (),
        applies=lambda _ctx: True,
        apply=lambda _ctx, _answers: None,
    )


# -----------------------------------------------------------------------------
# CAL welfare acknowledgement
# -----------------------------------------------------------------------------


def ack_step() -> Step:
    def explanation(ctx: StepContext) -> list[str]:

        lines = _wizard.CAL_ARTICLE_4_SUMMARY.splitlines()
        if ctx.extra.get("defaults"):
            lines.append("")
            lines.append(
                f"[--defaults] Recording the acknowledgement '{_wizard.ACK_PHRASE}' on the"
            )
            lines.append(
                "non-interactive default path. By running --defaults you affirm these terms."
            )
        return lines

    def fields(ctx: StepContext) -> tuple[Field, ...]:

        default = _wizard.ACK_PHRASE if ctx.extra.get("defaults") else ""
        return (
            Field(
                "ack",
                f"Type '{_wizard.ACK_PHRASE}' to confirm you accept these obligations\n"
                "(anything else aborts without writing any config):\n"
                "> ",
                "text",
                default=default,
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:

        answer = (answers.get("ack") or "").strip()
        ctx.extra["acknowledged"] = answer == _wizard.ACK_PHRASE

    return Step(
        id="welfare-acknowledgement",
        title="CAL welfare acknowledgement (required)",
        explanation=explanation,
        fields=fields,
        applies=lambda _ctx: True,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Deployment tier
# -----------------------------------------------------------------------------


def tier_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return ctx.extra.get("tier_rec") is not None and not ctx.extra.get("defaults")

    def explanation(ctx: StepContext) -> list[str]:
        rec = ctx.extra["tier_rec"]
        label = getattr(rec, "profile", f"tier{getattr(rec, 'tier', '')}")
        lines = [
            f"  Recommended tier: {label}",
            f"  Reason: {getattr(rec, 'reason', '')}",
        ]
        budget = getattr(rec, "memory_budget_gb", None)
        if budget is not None:
            lines.append(f"  Memory budget: {budget} GB")
        else:
            lines.append("  Memory budget: unknown")
        return lines

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        rec = ctx.extra["tier_rec"]
        label = getattr(rec, "profile", f"tier{getattr(rec, 'tier', '')}")
        existing = ctx.extra.get("existing_config") or {}
        default = _existing(existing, "deployment.tier", None) is not None
        return (
            Field(
                "record_tier",
                f"Record tier {label} for this install? It bounds backends and devices "
                f"for this hardware and never changes which modules are enabled; the pre-boot "
                f"check reports any enabled module this tier cannot run.",
                "bool",
                default=default,
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        if answers.get("record_tier"):
            rec = ctx.extra["tier_rec"]
            label = getattr(rec, "profile", f"tier{getattr(rec, 'tier', '')}")
            ctx.config.setdefault("deployment", {})["tier"] = label

    return Step(
        id="deployment-tier",
        title="Deployment tier recommendation",
        explanation=explanation,
        fields=fields,
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Accelerator/runtime mismatch
# -----------------------------------------------------------------------------


def accel_mismatch_step() -> Step:
    """Wrap the existing mismatch helper as a Step.

    The helper's interactive corrective-install loop cannot be expressed as
    declarative fields, so this Step exposes zero fields and performs the
    interaction directly through ``ctx.extra["input_fn"]``.  This is the one
    allowed exception to the step-model field pattern.
    """

    def apply(ctx: StepContext, _answers: dict[str, Any]) -> None:

        info = _wizard._accel_mismatch_step(
            input_fn=ctx.extra["input_fn"],
            line=_make_line(ctx),
            host=ctx.host,
            torch_cuda_probes=ctx.extra.get("torch_cuda_probes"),
            corrective_install_fn=ctx.extra.get("corrective_install_fn"),
            wheel_index_url=ctx.extra.get("wheel_index_url"),
            defaults=ctx.extra.get("defaults", False),
        )
        ctx.extra["mismatch_info"] = info

    return Step(
        id="accelerator-mismatch",
        title="Accelerator/runtime compatibility check",
        explanation=lambda _ctx: [],
        fields=lambda _ctx: (),
        applies=lambda _ctx: True,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Module selection
# -----------------------------------------------------------------------------


def module_preset_step() -> Step:
    def _recommended(ctx: StepContext) -> tuple[str, str]:
        return _wizard.recommend_preset(ctx.extra.get("tier_rec"))

    def explanation(ctx: StepContext) -> list[str]:
        preset, why = _recommended(ctx)
        label = "full entity" if preset == "full" else "base thesis"
        return [f"Recommended: {label} — {why}."]

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        rec_default = "f" if _recommended(ctx)[0] == "full" else "b"
        default = _module_preset_default(ctx, rec_default)
        return (
            Field(
                "preset",
                "  modules: [b]ase thesis, [f]ull entity, or [c]ustom?",
                "choice",
                default=default,
                choices=("b", "f", "c"),
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:

        choice = answers.get("preset", "b")
        preset, why = _wizard.recommend_preset(ctx.extra.get("tier_rec"))
        if choice == "b":
            modules = _wizard.base_thesis_modules()
            modules["echo"] = False
            ctx.config["modules"] = modules
            label = "base thesis"
        elif choice == "f":
            modules = _wizard.FULL_ENTITY_MODULES.copy()
            modules["echo"] = False
            ctx.config["modules"] = modules
            label = "full entity"
        else:
            label = "custom"
            seed = (
                _wizard.FULL_ENTITY_MODULES.copy()
                if preset == "full"
                else _wizard.base_thesis_modules()
            )
            ctx.extra["custom_modules_seed"] = seed
        ctx.extra["module_preset"] = label
        ctx.extra["preset_reason"] = why

        if ctx.extra.get("defaults") and choice in ("b", "f"):
            line = _make_line(ctx)
            line(f"[--defaults] module preset: {label} ({why})")
            for m in _wizard.MODULE_ORDER:
                line(f"  {m} = {str(ctx.config['modules'].get(m, False)).lower()}")

    return Step(
        id="module-preset",
        title="Module selection",
        explanation=explanation,
        fields=fields,
        applies=lambda _ctx: True,
        apply=apply,
    )


def custom_modules_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return ctx.extra.get("module_preset") == "custom"

    def explanation(_ctx: StepContext) -> list[str]:
        return [
            "Enable each module? (defaults shown; perception/echo/mundus default off)"
        ]

    def fields(ctx: StepContext) -> tuple[Field, ...]:

        seed = ctx.extra.get("custom_modules_seed") or _wizard.FULL_ENTITY_MODULES.copy()
        existing = ctx.extra.get("existing_config") or {}
        return tuple(
            Field(
                m,
                f"  enable {m}?",
                "bool",
                default=_existing(existing, f"modules.{m}", seed.get(m, False)),
            )
            for m in _wizard.MODULE_ORDER
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:

        seed = ctx.extra.get("custom_modules_seed") or _wizard.FULL_ENTITY_MODULES.copy()
        modules: dict[str, bool] = {}
        for m in _wizard.MODULE_ORDER:
            modules[m] = bool(answers.get(m, seed.get(m, False)))
        modules["echo"] = False
        ctx.config["modules"] = modules
        ctx.extra["module_preset"] = "custom"

    return Step(
        id="module-custom",
        title="Module selection",
        explanation=explanation,
        fields=fields,
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Model / voice / STT
# -----------------------------------------------------------------------------


def lingua_model_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return bool((ctx.config.get("modules") or {}).get("lingua"))

    def explanation(ctx: StepContext) -> list[str]:
        models = (ctx.extra.get("discovered") or {}).get("served_models") or []
        if models:
            return [f"  Models served: {', '.join(str(m) for m in models)}"]
        return []

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        existing = ctx.extra.get("existing_config") or {}
        shipped = ctx.extra.get("shipped_config") or {}
        default = _existing(
            existing,
            "lingua.model_id",
            str((shipped.get("lingua") or {}).get("model_id", "")),
        )
        return (
            Field(
                "model_id",
                "  [lingua].model_id",
                "text",
                default=default,
            ),
        )

    def apply(_ctx: StepContext, answers: dict[str, Any]) -> None:
        # apply is bound to the current config dict via StepContext mutation.
        config = _ctx.config
        config.setdefault("lingua", {})["model_id"] = answers.get("model_id", "")

    return Step(
        id="lingua-model",
        title="Model / voice / STT",
        explanation=explanation,
        fields=fields,
        applies=applies,
        apply=apply,
    )


def _vox_backend(ctx: StepContext) -> str:
    shipped = ctx.extra.get("shipped_config") or {}
    return str((shipped.get("vox") or {}).get("backend", "chatterbox")).strip().lower()


def vox_voice_step() -> Step:
    # Applies whenever Vox is on. Only the Chatterbox backend needs a voice id;
    # any other backend asks nothing and says so, as the terminal wizard does.
    def applies(ctx: StepContext) -> bool:
        return bool((ctx.config.get("modules") or {}).get("vox"))

    def explanation(ctx: StepContext) -> list[str]:
        if _vox_backend(ctx) != "chatterbox":
            return [
                "  Vox speaks through sherpa-onnx Kokoro (preset speaker "
                "[vox].sherpa_speaker_id); no Chatterbox voice needed."
            ]
        voices = (ctx.extra.get("discovered") or {}).get("voices") or []
        if voices:
            return [f"  Chatterbox voices: {', '.join(str(v) for v in voices)}"]
        return []

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        if _vox_backend(ctx) != "chatterbox":
            return ()
        existing = ctx.extra.get("existing_config") or {}
        shipped = ctx.extra.get("shipped_config") or {}
        voices = (ctx.extra.get("discovered") or {}).get("voices") or []
        default = (
            _existing(
                existing,
                "vox.predefined_voice_id",
                str((shipped.get("vox") or {}).get("predefined_voice_id", "")),
            )
            or (str(voices[0]) if voices else "")
        )

        def _require_voice(value: Any) -> str | None:
            return None if value else "a voice id is required when vox is enabled."

        return (
            Field(
                "voice_id",
                "  [vox].predefined_voice_id (REQUIRED when vox is enabled)",
                "text",
                default=default,
                validate=_require_voice,
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        if _vox_backend(ctx) != "chatterbox":
            return
        voice_id = answers.get("voice_id", "")
        if voice_id:
            ctx.config.setdefault("vox", {})["predefined_voice_id"] = voice_id
        else:
            ctx.config.setdefault("modules", {})["vox"] = False
            _make_line(ctx)("    no voice id available; disabling vox.")

    return Step(
        id="vox-voice",
        title="Model / voice / STT",
        explanation=explanation,
        fields=fields,
        applies=applies,
        apply=apply,
    )


def audition_stt_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        if not (ctx.config.get("modules") or {}).get("audition"):
            return False
        shipped = ctx.extra.get("shipped_config") or {}
        backend = str((shipped.get("audition") or {}).get("backend", "speaches")).strip().lower()
        return backend == "speaches"

    def explanation(ctx: StepContext) -> list[str]:
        stt_models = (ctx.extra.get("discovered") or {}).get("stt_models") or []
        if stt_models:
            return [f"  Speaches STT models: {', '.join(str(s) for s in stt_models)}"]
        return []

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        existing = ctx.extra.get("existing_config") or {}
        shipped = ctx.extra.get("shipped_config") or {}
        default = _existing(
            existing,
            "audition.stt_model",
            str((shipped.get("audition") or {}).get("stt_model", "")),
        )
        return (
            Field(
                "stt_model",
                "  [audition].stt_model",
                "text",
                default=default,
            ),
        )

    def apply(_ctx: StepContext, answers: dict[str, Any]) -> None:
        config = _ctx.config
        config.setdefault("audition", {})["stt_model"] = answers.get("stt_model", "")

    return Step(
        id="audition-stt",
        title="Model / voice / STT",
        explanation=explanation,
        fields=fields,
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Stage-2 trainer provisioning
# -----------------------------------------------------------------------------


def trainer_provisioning_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return not ctx.extra.get("defaults") and ctx.extra.get("probe_trainer") is not None

    def apply(ctx: StepContext, _answers: dict[str, Any]) -> None:
        from kaine.setup.trainer_provisioning import trainer_guidance

        _wizard._trainer_provisioning_step(
            ctx.config,
            input_fn=ctx.extra["input_fn"],
            line=_make_line(ctx),
            host=ctx.host,
            probe_trainer=ctx.extra["probe_trainer"],
            guidance_fn=trainer_guidance,
        )

    return Step(
        id="trainer-provisioning",
        title="Sleep-cycle voice-alignment trainer (Stage 2 / optional)",
        explanation=lambda _ctx: [],
        fields=lambda _ctx: (),
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# CL1 substrate plugin
# -----------------------------------------------------------------------------


def cl1_substrate_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return not ctx.extra.get("defaults")

    def apply(ctx: StepContext, _answers: dict[str, Any]) -> None:

        _wizard._cl1_substrate_step(
            ctx.config,
            input_fn=ctx.extra["input_fn"],
            line=_make_line(ctx),
        )

    return Step(
        id="cl1-substrate",
        title="Biological substrate plugin (optional, off by default)",
        explanation=lambda _ctx: [],
        fields=lambda _ctx: (),
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# Research metrics
# -----------------------------------------------------------------------------


def research_opt_in_step() -> Step:
    def explanation(_ctx: StepContext) -> list[str]:
        return [
            "KAINE can submit NUMERIC METRICS ONLY (never speech, transcripts,",
            "memories, or any conversation content) to the project, operator-initiated",
            "via `python -m kaine.research`. Nothing is ever transmitted automatically.",
        ]

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        existing = ctx.extra.get("existing_config") or {}
        default = bool(_existing(existing, "research_submission.enabled", False))
        return (
            Field(
                "opt_in",
                "Opt in to metrics-only research submission?",
                "bool",
                default=default,
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        if answers.get("opt_in"):
            ctx.extra["research_opted_in"] = True

    return Step(
        id="research-opt-in",
        title="Research metrics (opt-in)",
        explanation=explanation,
        fields=fields,
        applies=lambda _ctx: True,
        apply=apply,
    )


def research_recipient_step() -> Step:
    def applies(ctx: StepContext) -> bool:
        return ctx.extra.get("research_opted_in") is True

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        existing = ctx.extra.get("existing_config") or {}
        default = _existing(
            existing,
            "research_submission.recipient",
            "kaine.one@tuta.com",
        )
        return (
            Field(
                "recipient",
                "  recipient email",
                "text",
                default=default,
            ),
        )

    def apply(_ctx: StepContext, answers: dict[str, Any]) -> None:
        recipient = answers.get("recipient", "kaine.one@tuta.com")
        rs = _ctx.config.setdefault("research_submission", {})
        rs["enabled"] = True
        rs["tier"] = "metrics"
        rs["recipient"] = recipient
        _ctx.config.setdefault("transfer", {})["recipient"] = recipient

    return Step(
        id="research-recipient",
        title="Research metrics (opt-in)",
        explanation=lambda _ctx: [],
        fields=fields,
        applies=applies,
        apply=apply,
    )


# -----------------------------------------------------------------------------
# State encryption
# -----------------------------------------------------------------------------


def encryption_step() -> Step:
    def explanation(_ctx: StepContext) -> list[str]:
        return [
            "Optional AES-256-GCM encryption-at-rest for persisted cognitive state.",
            "If enabled, the entity refuses to boot unless a 32-byte key is available",
            "via the KAINE_STATE_KEY environment variable (fail-closed).",
        ]

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        existing = ctx.extra.get("existing_config") or {}
        default = bool(_existing(existing, "security.state_encryption.enabled", False))
        return (
            Field(
                "enabled",
                "Enable state encryption at rest?",
                "bool",
                default=default,
            ),
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        if answers.get("enabled"):
            ctx.config.setdefault("security", {}).setdefault("state_encryption", {})[
                "enabled"
            ] = True
            line = _make_line(ctx)
            line(
                "  Remember to export KAINE_STATE_KEY (32 raw bytes, or base64/hex of"
            )
            line(
                "  32 bytes) before booting, or the entity will refuse to start."
            )

    return Step(
        id="state-encryption",
        title="State encryption (opt-in)",
        explanation=explanation,
        fields=fields,
        applies=lambda _ctx: True,
        apply=apply,
    )
