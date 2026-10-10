# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Step logic for the first-run wizard.

This module is deliberately pure-ish: :func:`run_wizard` takes an answer source
(``input_fn``), an output sink (``out``), a host description (the result of
:func:`kaine.hardware.describe_host`), and a service-probe callable. It returns a
:class:`WizardResult` holding the assembled operator-config dict and whether the
operator gave the required CAL welfare acknowledgement. It performs NO I/O of its
own beyond ``input_fn``/``out``: no file writes, no network, no subprocess, no
boot. The ``__main__`` module wires the real input, probes, extras install, and
the operator-config write.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from kaine.setup.hardware_steps import (
    consent_step,
    device_step,
    inventory_step,
    load_footprint_catalogue,
    shared_services_step,
)
from kaine.setup.steps import StepContext, run_step
from kaine.setup.wizard_core import (
    ACK_PHRASE,
    CAL_ARTICLE_4_SUMMARY,
    FULL_ENTITY_MODULES,
    MODULE_ORDER,
    WizardResult,
    base_thesis_modules,
    implied_extras,
    propose_device_assignments,
    recommend_preset,
)

# Re-exported from wizard_core so existing imports of these names keep working.
__all__ = [
    "ACK_PHRASE",
    "CAL_ARTICLE_4_SUMMARY",
    "FULL_ENTITY_MODULES",
    "MODULE_ORDER",
    "WizardResult",
    "base_thesis_modules",
    "implied_extras",
    "propose_device_assignments",
    "recommend_preset",
    "run_wizard",
]

from kaine.setup.wizard_steps import (
    accel_mismatch_step,
    ack_step,
    audition_stt_step,
    cl1_substrate_step,
    custom_modules_step,
    encryption_step,
    lingua_model_step,
    module_preset_step,
    orientation_step,
    research_opt_in_step,
    research_recipient_step,
    tier_step,
    trainer_provisioning_step,
    vox_voice_step,
)


def run_wizard(
    *,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    host: dict[str, Any],
    shipped_config: dict[str, Any],
    probe_services: Callable[[], dict[str, Any]] | None = None,
    probe_trainer: Callable[..., tuple[bool, str]] | None = None,
    torch_cuda_probes: dict[str, Any] | None = None,
    corrective_install_fn: Callable[[str], bool] | None = None,
    wheel_index_url: str | None = None,
    device_consumers_fn: Callable[[], list[dict]] | None = None,
    defaults: bool = False,
    recommend_tier_fn: Callable[[], Any] | None = None,
    services_up_fn: Callable[[], dict[str, bool]] | None = None,
    storage_old_root: Path | None = None,
    existing_config: dict[str, Any] | None = None,
) -> WizardResult:
    """Run the wizard's step logic and return the assembled operator-config.

    ``services_up_fn`` detects which external services are already listening so
    the wizard can skip shared-service prompts for things that are already up.

    ``storage_old_root`` is the current data root, or the working directory, whose
    data may be relocated.

    ``device_consumers_fn`` returns per-device process consumers used by the
    hardware inventory step.

    ``existing_config`` is the parsed current operator file (if any). Field
    defaults prefer the existing value for the key each field owns, so a
    re-run with empty answers reproduces the previous configuration.

    Parameters
    ----------
    input_fn:
        Returns the operator's answer for a prompt. In ``defaults`` mode it is
        never consulted for choices (only the recorded ack note is synthetic).
    out:
        Writes a line of operator-facing text.
    host:
        Result of :func:`kaine.hardware.describe_host`.
    shipped_config:
        The parsed shipped ``config/kaine.toml`` (used to read defaults like
        capture flags / backends when computing implied extras).
    probe_services:
        Optional callable returning discovered service options, e.g.
        ``{"served_models": [...], "voices": [...], "stt_models": [...]}``.
        Skipped entirely in ``defaults`` mode and when None.
    probe_trainer:
        Optional real detection probe for the external voice-alignment trainer
        interpreter. When None or in ``defaults`` mode the optional Stage-2
        trainer step is skipped.
    recommend_tier_fn:
        Optional callable returning a :class:`kaine.hardware.TierRecommendation`.
    defaults:
        Non-interactive mode for tests/CI.
    existing_config:
        Parsed current operator file used to pre-fill defaults and for the
        merge-on-save diff.
    """
    cfg: dict[str, Any] = {}
    if existing_config is None:
        existing_config = {}

    def line(text: str = "") -> None:
        out(text + "\n")

    ctx = StepContext(
        config=cfg,
        host=host,
        extra={
            "input_fn": input_fn,
            "out": line,
            "defaults": defaults,
            "shipped_config": shipped_config,
            "existing_config": existing_config,
            "probe_trainer": probe_trainer,
            "torch_cuda_probes": torch_cuda_probes,
            "corrective_install_fn": corrective_install_fn,
            "wheel_index_url": wheel_index_url,
        },
    )

    # --- Orientation --------------------------------------------------------
    run_step(
        orientation_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- CAL welfare acknowledgement (REQUIRED) -----------------------------
    run_step(
        ack_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    if not ctx.extra.get("acknowledged"):
        line(
            "\nAcknowledgement not given; aborting. No configuration was written."
        )
        return WizardResult(acknowledged=False)

    # Nothing is probed or scanned before the acknowledgement is given.
    discovered: dict[str, Any] = {}
    if not defaults and probe_services is not None:
        try:
            discovered = probe_services() or {}
        except Exception:
            discovered = {}
    ctx.extra.update(
        {
            "discovered": discovered,
            "consumers": device_consumers_fn() if device_consumers_fn else None,
            "catalogue": load_footprint_catalogue(),
            "floor_gb": float(
                ((shipped_config.get("gpu_preflight") or {}).get(
                    "min_free_vram_gb", 2.0
                ))
            ),
            "services_up": (services_up_fn() if services_up_fn else {}),
        }
    )
    # The tier recommendation feeds the tier step and the module preset.
    tier_rec = None
    if recommend_tier_fn is not None:
        try:
            tier_rec = recommend_tier_fn()
        except Exception as exc:
            if not defaults:
                line(f"  Tier recommendation unavailable ({exc}).")
    ctx.extra["tier_rec"] = tier_rec

    # --- Hardware scan + device assignments ---------------------------------
    run_step(
        inventory_step,
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    run_step(
        consent_step,
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    run_step(
        device_step(propose_device_assignments),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    run_step(
        shared_services_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Storage ------------------------------------------------------------
    from kaine.setup.storage_step import relocation_step, storage_step

    ctx.extra["min_free_gb"] = float(
        ((shipped_config.get("storage") or {}).get("min_free_gb", 20.0))
    )
    ctx.extra["old_root"] = storage_old_root
    if storage_old_root is not None:
        run_step(
            storage_step,
            ctx,
            input_fn=input_fn,
            out=out,
            defaults=defaults,
        )
        run_step(
            relocation_step,
            ctx,
            input_fn=input_fn,
            out=out,
            defaults=defaults,
        )
    if "relocation_error" in ctx.extra:
        out(ctx.extra["relocation_error"] + "\n")
    if "relocation_note" in ctx.extra:
        out(ctx.extra["relocation_note"] + "\n")

    # --- Deployment tier recommendation --------------------------------------
    run_step(
        tier_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Accelerator/runtime mismatch check ----------------------------------
    run_step(
        accel_mismatch_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Module selection ---------------------------------------------------
    run_step(
        module_preset_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    if ctx.extra.get("module_preset") == "custom":
        run_step(
            custom_modules_step(),
            ctx,
            input_fn=input_fn,
            out=out,
            defaults=defaults,
        )

    # --- Model / voice / STT ------------------------------------------------
    run_step(
        lingua_model_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    run_step(
        vox_voice_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    run_step(
        audition_stt_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Stage-2 trainer provisioning ---------------------------------------
    run_step(
        trainer_provisioning_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Research metrics (opt-in) ------------------------------------------
    run_step(
        research_opt_in_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )
    if ctx.extra.get("research_opted_in"):
        run_step(
            research_recipient_step(),
            ctx,
            input_fn=input_fn,
            out=out,
            defaults=defaults,
        )

    # --- State encryption (opt-in) ------------------------------------------
    run_step(
        encryption_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    # --- Optional CL1 substrate plugin --------------------------------------
    run_step(
        cl1_substrate_step(),
        ctx,
        input_fn=input_fn,
        out=out,
        defaults=defaults,
    )

    line(f"Module preset: {ctx.extra.get('module_preset', 'custom')}")

    extras = implied_extras(cfg.get("modules", {}), shipped_config)

    mismatch_info = ctx.extra.get("mismatch_info", {})
    return WizardResult(
        acknowledged=True,
        config=cfg,
        extras=extras,
        mismatch_verdict=mismatch_info.get("verdict"),
        corrective_install_accepted=mismatch_info.get("accepted"),
        corrective_install_ran=mismatch_info.get("install_ran", False),
        corrective_install_ok=mismatch_info.get("install_ok"),
    )
