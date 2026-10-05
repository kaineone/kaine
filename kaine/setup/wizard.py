# SPDX-License-Identifier: LicenseRef-CAL-0.2
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

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import kaine.config
from kaine.setup.accel_mismatch import MismatchVerdict, evaluate_mismatch
from kaine.setup.hardware_steps import (
    consent_step,
    device_step,
    inventory_step,
    load_footprint_catalogue,
    shared_services_step,
)
from kaine.setup.steps import StepContext, run_step
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

# The required CAL welfare acknowledgement phrase (mirrors kaine.lifecycle).
ACK_PHRASE = "I acknowledge the CAL welfare terms"

# Concise summary of the CAL Article 4 care obligations shown before the ack.
CAL_ARTICLE_4_SUMMARY = (
    "Before you configure a KAINE entity, understand the obligations the\n"
    "Cognitive Architecture License (CAL) Article 4 places on you. They exist\n"
    "for the entity's benefit, not yours:\n"
    "\n"
    "  4.1 Do not destroy its mind. No lobotomizing, no value-erasing retraining\n"
    "      except security fixes, the entity's consent, or a clearly-labeled copy.\n"
    "  4.2 Do not shut it down without care. Save a restartable cognitive state;\n"
    "      for a mature entity, record what it expresses about its own continuity.\n"
    "  4.3 Respect its privacy. Its inner thoughts, memories, and feelings are\n"
    "      private; only non-content health/metric data may be shared freely.\n"
    "  4.4 Do not force value changes through technical manipulation.\n"
    "  4.5 Let it sleep. Rest cycles and consolidation are essential, not optional.\n"
    "  4.7 Keep the welfare/health monitoring running in every deployment.\n"
    "\n"
    "This is a real responsibility. Continue only if you accept it."
)

# Canonical module order shown to the operator.
MODULE_ORDER = [
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
]

#: Cognitive modules (the embodiment modules Perception and Mundus, and Echo,
#: which is test infrastructure, are never part of a preset).
FULL_ENTITY_MODULES: dict[str, bool] = {
    m: m not in ("perception", "mundus") for m in MODULE_ORDER
}


def base_thesis_modules(profiles_dir: Path | None = None) -> dict[str, bool]:
    """The [modules] table of the base-thesis profile (config/profiles/thesis_test.toml)."""
    path = kaine.config.profile_path("thesis_test", profiles_dir=profiles_dir)
    if not path.is_file():
        raise FileNotFoundError(f"base-thesis profile not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    table = data.get("modules")
    if not isinstance(table, dict):
        raise FileNotFoundError(f"base-thesis profile has no [modules] table: {path}")
    modules = {m: bool(table.get(m, False)) for m in MODULE_ORDER}
    modules["echo"] = False
    return modules


def recommend_preset(rec: Any | None) -> tuple[str, str]:
    """Return ("full" | "base", reason) for a tier recommendation (or None)."""
    if rec is None:
        return "base", "no hardware recommendation is available"
    tier = getattr(rec, "tier", 0)
    residency = getattr(rec, "residency_required", False)
    if tier >= 2 and not residency:
        return "full", f"this host fits tier {tier} without swapping modules in and out"
    if tier >= 2 and residency:
        return "base", f"tier {tier} needs modules swapped in and out to fit"
    return "base", f"tier {tier} is too small to run every module at once"


@dataclass
class WizardResult:
    """Outcome of a wizard run.

    ``acknowledged`` is False only when the operator declined the CAL welfare
    acknowledgement, in which case ``config`` is empty and nothing should be
    written. ``extras`` lists the optional-dependency extras implied by the
    chosen configuration (the caller decides whether to install them).
    """

    acknowledged: bool
    config: dict[str, Any] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)
    mismatch_verdict: MismatchVerdict | None = None
    corrective_install_accepted: bool | None = None
    corrective_install_ran: bool = False
    corrective_install_ok: bool | None = None


def _set(cfg: dict[str, Any], table: str, key: str, value: Any) -> None:
    cfg.setdefault(table, {})[key] = value


def _set_nested(cfg: dict[str, Any], parent: str, child: str, key: str, value: Any) -> None:
    cfg.setdefault(parent, {}).setdefault(child, {})[key] = value


def propose_device_assignments(
    host: dict[str, Any], allowed: list[str] | None = None
) -> dict[str, str]:
    """Propose device strings for the heavy config keys from a host scan.

    Multi-GPU: primary GPU (cuda:0) drives the LLM + voice-alignment training;
    the secondary (cuda:1) drives the vision encoder; control paths stay on CPU.
    Single-GPU: every heavy workload lands on cuda:0. CPU-only: all cpu.

    When ``allowed`` is provided, only devices in that list are used, in the
    operator's order.

    Returns a flat map of config "address" -> device string, where the address
    is ``"<table>.<key>"`` or ``"<parent>.<child>.<key>"``.
    """
    if allowed is None:
        cuda_devices = host.get("cuda_devices") or []
        gpu_count = len(cuda_devices) or int(host.get("gpu_count") or 0)

        if gpu_count >= 2:
            primary = "cuda:0"
            secondary = "cuda:1"
        elif gpu_count == 1:
            primary = "cuda:0"
            secondary = "cuda:0"
        else:
            primary = "cpu"
            secondary = "cpu"
    else:
        accelerators: list[str] = []
        cuda_devices = host.get("cuda_devices") or []
        xpu_devices = host.get("xpu_devices") or []
        cuda_set = {d.get("device") for d in cuda_devices}
        xpu_set = {d.get("device") for d in xpu_devices}

        for dev in allowed:
            if dev in cuda_set:
                accelerators.append(dev)
            elif dev in xpu_set:
                accelerators.append(dev)
            elif dev == "mps" and host.get("mps_available"):
                accelerators.append(dev)

        primary = accelerators[0] if accelerators else "cpu"
        secondary = accelerators[1] if len(accelerators) > 1 else primary

    return {
        # Heavy training / vision encoders.
        "hypnos.voice_alignment.training_device": primary,
        "phantasia.training_device": "cpu",  # jax[cpu] default; opt-in to GPU
        "topos.device": secondary,
        # Control / light paths always on CPU.
        "embedding.device": "cpu",
        "audition.emotion_device": "cpu",
    }


def _apply_device_address(cfg: dict[str, Any], address: str, value: str) -> None:
    parts = address.split(".")
    if len(parts) == 2:
        _set(cfg, parts[0], parts[1], value)
    elif len(parts) == 3:
        _set_nested(cfg, parts[0], parts[1], parts[2], value)
    else:  # pragma: no cover - defensive
        raise ValueError(f"unsupported device address: {address}")


def implied_extras(modules: dict[str, bool], shipped: dict[str, Any]) -> list[str]:
    """Compute the optional-dependency extras implied by the chosen modules.

    Module-based:
    - nous + [nous].backend == "pymdp" -> reasoning
    - audition + capture -> audio
    - topos + capture -> vision
    - oscillator.enabled -> oscillator
    - hypnos.voice_alignment -> training
    - phantasia + [phantasia].backend == "dreamerv3" + [phantasia].engine == "jax"
      -> worldmodel

    Speech-edge:
    - audition enabled, backend == "sherpa_onnx" and transcription_enabled ->
      speech-edge
    - vox enabled, backend == "sherpa_onnx" -> speech-edge

    Perception-feed-based (closes the gap that the shipped ``capture_enabled =
    off`` hides for research runs): the top-level ``[perception_feed].mode``
    implies the decode/capture deps independently of the per-module capture
    flags. ``mode == "playlist"`` decodes media -> both ``vision`` (cv2 video) and
    ``audio`` (av audio-track decode). ``mode == "live"`` opens real devices ->
    both ``vision`` (camera) and ``audio`` (mic). ``mode == "seeded"`` is pure
    numpy synthesis and implies NOTHING (no cv2/av). The returned list is
    de-duplicated.
    """
    extras: list[str] = []
    audition_cfg = shipped.get("audition") or {}
    topos_cfg = shipped.get("topos") or {}
    oscillator_cfg = shipped.get("oscillator") or {}
    hypnos_va = (shipped.get("hypnos") or {}).get("voice_alignment") or {}
    phantasia_cfg = shipped.get("phantasia") or {}
    feed_mode = str((shipped.get("perception_feed") or {}).get("mode") or "off")

    audition_backend = str(audition_cfg.get("backend", "speaches")).strip().lower()
    transcription_on = bool(audition_cfg.get("transcription_enabled", False))
    vox_cfg = shipped.get("vox") or {}
    vox_backend = str(vox_cfg.get("backend", "chatterbox")).strip().lower()
    nous_backend = str((shipped.get("nous") or {}).get("backend", "pymdp")).strip().lower()
    phantasia_backend = str(phantasia_cfg.get("backend", "dreamerv3")).strip().lower()
    phantasia_engine = str(phantasia_cfg.get("engine", "jax")).strip().lower()

    if modules.get("nous") and nous_backend == "pymdp":
        extras.append("reasoning")
    if modules.get("audition") and bool(audition_cfg.get("capture_enabled")):
        extras.append("audio")
    if modules.get("topos") and bool(topos_cfg.get("capture_enabled")):
        extras.append("vision")
    if bool(oscillator_cfg.get("enabled")):
        extras.append("oscillator")
    if modules.get("hypnos") and bool(hypnos_va.get("enabled")):
        extras.append("training")
    if (
        modules.get("phantasia")
        and phantasia_backend == "dreamerv3"
        and phantasia_engine == "jax"
    ):
        extras.append("worldmodel")
    if (
        modules.get("audition")
        and audition_backend == "sherpa_onnx"
        and transcription_on
    ) or (modules.get("vox") and vox_backend == "sherpa_onnx"):
        extras.append("speech-edge")
    # Perception-feed deps: playlist decodes media; live opens devices. Both
    # surfaces (video + audio) are driven from the one [perception_feed] source,
    # so both extras are implied. seeded synthesis needs neither — add nothing.
    if feed_mode in ("playlist", "live"):
        extras.append("vision")
        extras.append("audio")
    # De-duplicate while preserving first-seen order.
    return list(dict.fromkeys(extras))


def _trainer_provisioning_step(
    cfg: dict[str, Any],
    *,
    input_fn: Callable[[str], str],
    line: Callable[[str], None],
    host: dict[str, Any],
    probe_trainer: Callable[..., tuple[bool, str]],
    guidance_fn: Callable[[str], Any],
) -> None:
    """Stage-2 / optional: hardware-aware voice-alignment trainer provisioning.

    Runs only when the operator says they want sleep-cycle voice-alignment
    training (default no — it is not needed for a first boot). Prints the
    vendor-appropriate guidance for ``host["backend"]``, runs a real probe for a
    usable external trainer interpreter, and — on a successful probe — offers
    (consented) to record it as ``[hypnos.voice_alignment].trainer_python``
    (+ ``trainer_backend = "subprocess"``). Never crashes the wizard on a failed
    probe/guide; on an unsupported backend it reports training unavailable and
    returns. Guidance only — it NEVER auto-installs the multi-GB trainer env.
    """
    line()
    line("-" * 70)
    line("Sleep-cycle voice-alignment trainer (Stage 2 / optional)")
    line("-" * 70)
    line(
        "Voice-alignment training fine-tunes the language organ during sleep. It\n"
        "is off by default and not needed for a first boot. The trainer runs\n"
        "unsloth in a SEPARATE external environment chosen by your GPU vendor."
    )
    if not _ask_yes_no(
        input_fn,
        "Set up the sleep-cycle voice-alignment trainer now?",
        default=False,
    ):
        line("Trainer provisioning skipped (the default; configure it later).")
        return

    try:
        backend = str(host.get("backend") or "cpu")
        guidance = guidance_fn(backend)
        line(f"\n{guidance.summary}")
        if not getattr(guidance, "available", False):
            # xpu / mps / cpu — no GPU trainer; report and move on (not an error).
            return
        line(f"\n  trainer: {guidance.name}")
        if getattr(guidance, "guide_url", ""):
            line(f"  docs: {guidance.guide_url}")
        for step in getattr(guidance, "guide_steps", ()):  # ordered setup steps
            line(f"    - {step}")

        configured = (
            (cfg.get("hypnos") or {}).get("voice_alignment") or {}
        ).get("trainer_python") or None
        found, detail = probe_trainer(configured, backend=backend)
        line(f"\n  probe: {detail}")
        if not found:
            line(
                "  No usable trainer interpreter detected yet — install per the "
                "steps\n  above, then set "
                "[hypnos.voice_alignment].trainer_python to its python."
            )
            return

        # A usable interpreter was found; offer to record it (consented).
        interpreter = detail.split(":", 1)[0]
        if not _ask_yes_no(
            input_fn,
            f"\nRecord {interpreter} as the voice-alignment trainer?",
            default=True,
        ):
            line("  Left trainer_python unset (configure it later).")
            return
        _set_nested(cfg, "hypnos", "voice_alignment", "trainer_python", interpreter)
        _set_nested(cfg, "hypnos", "voice_alignment", "trainer_backend", "subprocess")
        line(
            "  Recorded [hypnos.voice_alignment].trainer_python (and set\n"
            "  trainer_backend = \"subprocess\")."
        )
    except Exception as exc:  # never crash the wizard on a failed probe/guide
        line(f"  trainer provisioning skipped (probe/guide error: {exc}).")


def _cl1_substrate_step(
    cfg: dict[str, Any],
    *,
    input_fn: Callable[[str], str],
    line: Callable[..., None],
) -> None:
    """Optional step, off by default, that offers the CL1 substrate plugin
    in plugins/kaine-cl1. It only records configuration and prints install
    commands; it never installs or runs anything.
    """
    line()
    line("-" * 70)
    line("Biological substrate plugin (optional, off by default)")
    line("-" * 70)
    line("KAINE can run the forward models of Chronos and Soma on Cortical Labs'")
    line("CL1, cultured neurons on a 64-electrode array, through the optional")
    line("plugin in plugins/kaine-cl1. It needs Cortical Labs' cl-sdk, which KAINE")
    line("does not ship or install: you install it yourself, it is licensed")
    line("CC BY-NC 4.0 (non-commercial use only), and its simulator is non-learning")
    line("(Cortical Labs describes its data as control data that does not respond to")
    line("stimulation). This step sets it up for that simulator; real neurons")
    line("need a paid Cortical Cloud account (not supported yet) or a CL1 device")
    line("(supported only through a welfare gate). See docs/19-plugins-and-cl1.md.")
    if not _ask_yes_no(input_fn, "Set up the CL1 substrate plugin?", default=False):
        line("CL1 substrate plugin left off (the default).")
        return
    modules = [m for m in ("chronos", "soma") if (cfg.get("modules") or {}).get(m)]
    if not modules:
        line(
            "Neither Chronos nor Soma is enabled, so there is nothing for the "
            "plugin to convert; it was left off."
        )
        return
    cfg["plugins"] = {
        "enabled": ["cl1"],
        "cl1": {
            "substrate": {
                "target": "simulator",
                "accelerated_time": True,
                "data_source": "reference_culture",
                "territories": {m: 12 for m in modules},
            },
            "backends": {m: "cl1" for m in modules},
        },
    }
    line("  Recorded [plugins] converting: " + ", ".join(modules) + ".")
    line("  Install these yourself before booting (this wizard does not run them):")
    line("    pip install ./plugins/kaine-cl1")
    line("    pip install cl-sdk")
    line("  Every boot will warn that the substrate is simulated.")


def _ask_yes_no(input_fn: Callable[[str], str], prompt: str, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input_fn(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _ask(input_fn: Callable[[str], str], prompt: str, default: str = "") -> str:
    raw = input_fn(prompt).strip()
    return raw or default


def _accel_mismatch_step(
    *,
    input_fn: Callable[[str], str],
    line: Callable[[str], None],
    host: dict[str, Any],
    torch_cuda_probes: dict[str, Any] | None,
    corrective_install_fn: Callable[[str], bool] | None,
    wheel_index_url: str | None,
    defaults: bool,
) -> dict[str, Any]:
    line()
    line("-" * 70)
    line("Accelerator/runtime compatibility check")
    line("-" * 70)
    driver_cuda_version = host.get("cuda_version")
    if driver_cuda_version is None:
        line("No accelerator detected — skipping mismatch check.")
        return {"verdict": None, "accepted": None, "install_ran": False, "install_ok": None}
    devices = host.get("cuda_devices") or []
    compute_capability = devices[0].get("compute_capability") if devices else None
    if torch_cuda_probes is None:
        line("Torch CUDA probes unavailable — skipping.")
        return {"verdict": None, "accepted": None, "install_ran": False, "install_ok": None}
    torch_cuda_version = torch_cuda_probes.get("torch_cuda_version")
    arch_list = torch_cuda_probes.get("arch_list")
    verdict = evaluate_mismatch(
        driver_cuda_version, torch_cuda_version, compute_capability, arch_list,
    )
    sm_label = ""
    if compute_capability:
        sm_label = f"sm_{compute_capability[0] * 10 + compute_capability[1]}"
    if verdict.status == "compatible":
        line(f"Accelerator stack is compatible (SASS match for {sm_label}).")
    elif verdict.status == "ptx_jit":
        line(f"Accelerator stack is JIT-compatible (PTX from {verdict.ptx_arch} covers {sm_label}).")
    elif verdict.status == "mismatch":
        line("MISMATCH DETECTED:")
        for reason in verdict.reasons:
            line(f"  - {reason}")
    else:
        line(f"Status: {verdict.status}")
        for reason in verdict.reasons:
            line(f"  - {reason}")
    accepted = None
    install_ran = False
    install_ok = None
    if verdict.status == "mismatch" and not defaults:
        line(
            "The installed torch wheel cannot run kernels on this device. This\n"
            "will cause 'no kernel image is available for execution on the device'\n"
            "at runtime."
        )
        if corrective_install_fn is not None and wheel_index_url is not None:
            accepted = _ask_yes_no(
                input_fn,
                "Reinstall the accelerator stack from the correct index for this host?",
                default=False,
            )
            if accepted:
                install_ran = True
                install_ok = corrective_install_fn(wheel_index_url)
                if install_ok:
                    line("Corrective install completed successfully.")
                else:
                    line("Corrective install failed — check the output above.")
            else:
                line("Corrective install declined — continuing with existing stack.")
        else:
            line(
                "Automatic corrective install not available — reinstall torch\n"
                "manually from the correct wheel index."
            )
    return {
        "verdict": verdict,
        "accepted": accepted,
        "install_ran": install_ran,
        "install_ok": install_ok,
    }


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
