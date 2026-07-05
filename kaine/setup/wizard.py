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

from dataclasses import dataclass, field
from typing import Any, Callable

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

# Module enable defaults for a safe, CPU-friendly first boot. Perception, echo,
# and mundus stay off; the conservative "think to itself first" set is enabled.
DEFAULT_MODULE_SET: dict[str, bool] = {
    "soma": True,
    "chronos": True,
    "thymos": True,
    "eidolon": True,
    "mnemos": True,
    "nous": False,
    "lingua": True,
    "hypnos": False,
    "topos": False,
    "praxis": False,
    "audition": False,
    "vox": False,
    "empatheia": False,
    "phantasia": False,
    "perception": False,
    "mundus": False,
    "echo": False,
}

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


def _set(cfg: dict[str, Any], table: str, key: str, value: Any) -> None:
    cfg.setdefault(table, {})[key] = value


def _set_nested(cfg: dict[str, Any], parent: str, child: str, key: str, value: Any) -> None:
    cfg.setdefault(parent, {}).setdefault(child, {})[key] = value


def propose_device_assignments(host: dict[str, Any]) -> dict[str, str]:
    """Propose device strings for the heavy config keys from a host scan.

    Multi-GPU: primary GPU (cuda:0) drives the LLM + voice-alignment training;
    the secondary (cuda:1) drives the vision encoder; control paths stay on CPU.
    Single-GPU: every heavy workload lands on cuda:0. CPU-only: all cpu.

    Returns a flat map of config "address" -> device string, where the address
    is ``"<table>.<key>"`` or ``"<parent>.<child>.<key>"``.
    """
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

    return {
        # Heavy training / vision encoders.
        "hypnos.voice_alignment.training_device": primary,
        "phantasia.training_device": "cpu",  # jax[cpu] default; opt-in to GPU
        "topos.device": secondary,
        # Control / light paths always on CPU.
        "mnemos.device": "cpu",
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

    Module-based: nous→reasoning, audition+capture→audio, topos+capture→vision,
    oscillator.enabled→oscillator, hypnos.voice_alignment→training,
    phantasia dreamerv3→worldmodel.

    Perception-feed-based (closes the gap that the shipped ``capture_enabled =
    off`` hides for research runs): the top-level ``[perception_feed].mode``
    implies the decode/capture deps independently of the per-module capture
    flags. ``mode == "playlist"`` decodes media → both ``vision`` (cv2 video) and
    ``audio`` (av audio-track decode). ``mode == "live"`` opens real devices →
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

    if modules.get("nous"):
        extras.append("reasoning")
    if modules.get("audition") and bool(audition_cfg.get("capture_enabled")):
        extras.append("audio")
    if modules.get("topos") and bool(topos_cfg.get("capture_enabled")):
        extras.append("vision")
    if bool(oscillator_cfg.get("enabled")):
        extras.append("oscillator")
    if modules.get("hypnos") and bool(hypnos_va.get("enabled")):
        extras.append("training")
    if modules.get("phantasia") and str(phantasia_cfg.get("backend")) == "dreamerv3":
        extras.append("worldmodel")
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


def _ask_yes_no(input_fn: Callable[[str], str], prompt: str, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input_fn(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _ask(input_fn: Callable[[str], str], prompt: str, default: str = "") -> str:
    raw = input_fn(prompt).strip()
    return raw or default


def run_wizard(
    *,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    host: dict[str, Any],
    shipped_config: dict[str, Any],
    probe_services: Callable[[], dict[str, Any]] | None = None,
    probe_trainer: Callable[..., tuple[bool, str]] | None = None,
    defaults: bool = False,
) -> WizardResult:
    """Run the wizard's step logic and return the assembled operator-config.

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
        interpreter (signature ``(interpreter, *, backend) -> (found, detail)``,
        e.g. :func:`kaine.setup.trainer_provisioning.probe_trainer`). When None
        or in ``defaults`` mode the optional Stage-2 trainer step is skipped.
    defaults:
        Non-interactive mode for tests/CI: records the ack as the default path,
        chooses a minimal safe module set, all-CPU devices, no metrics, no
        encryption.
    """
    cfg: dict[str, Any] = {}

    def line(text: str = "") -> None:
        out(text + "\n")

    # --- Step 1: orientation ------------------------------------------------
    line("=" * 70)
    line("KAINE first-run setup")
    line("=" * 70)
    line(
        "This wizard records your local choices to config/kaine.operator.toml\n"
        "(gitignored). It NEVER edits the shipped config/kaine.toml and NEVER\n"
        "boots the entity. It will set up: license acknowledgement, device\n"
        "assignments from a hardware scan, which modules to enable, the served\n"
        "model/voice/STT ids, optional dependency extras, opt-in research\n"
        "metrics, and state encryption."
    )

    # --- Step 2: CAL welfare acknowledgement (REQUIRED) ---------------------
    line()
    line("-" * 70)
    line("CAL welfare acknowledgement (required)")
    line("-" * 70)
    line(CAL_ARTICLE_4_SUMMARY)
    if defaults:
        line(
            f"\n[--defaults] Recording the acknowledgement '{ACK_PHRASE}' on the\n"
            "non-interactive default path. By running --defaults you affirm these terms."
        )
    else:
        ack = input_fn(
            f"\nType '{ACK_PHRASE}' to confirm you accept these obligations\n"
            "(anything else aborts without writing any config):\n> "
        ).strip()
        if ack != ACK_PHRASE:
            line(
                "\nAcknowledgement not given; aborting. No configuration was written."
            )
            return WizardResult(acknowledged=False)

    # --- Step 3: hardware scan + device assignments -------------------------
    line()
    line("-" * 70)
    line("Hardware scan")
    line("-" * 70)
    line(f"  backend: {host.get('backend')}   device: {host.get('device')}")
    cpu_count = host.get("cpu_count")
    if cpu_count:
        line(f"  CPU cores: {cpu_count}")
    cuda_devices = host.get("cuda_devices") or []
    if cuda_devices:
        for d in cuda_devices:
            line(
                f"  {d.get('device')}: {d.get('name')} "
                f"({d.get('total_vram_gb')} GB total, {d.get('free_vram_gb')} GB free)"
            )
    else:
        line("  no CUDA GPUs detected — heavy workloads will run on CPU")

    proposed = propose_device_assignments(host)
    line("\nProposed device assignments:")
    for address, dev in proposed.items():
        line(f"  {address} = {dev}")

    if not defaults and not _ask_yes_no(
        input_fn, "\nAccept these device assignments?", default=True
    ):
        for address in proposed:
            current = proposed[address]
            answer = _ask(
                input_fn,
                f"  device for {address} [{current}]: ",
                default=current,
            )
            proposed[address] = answer
    for address, dev in proposed.items():
        _apply_device_address(cfg, address, dev)

    # --- Step 4: module selection -------------------------------------------
    line()
    line("-" * 70)
    line("Module selection")
    line("-" * 70)
    modules: dict[str, bool] = {}
    if defaults:
        modules = {m: DEFAULT_MODULE_SET.get(m, False) for m in MODULE_ORDER}
        line("[--defaults] minimal safe first-boot set:")
        for m in MODULE_ORDER:
            line(f"  {m} = {str(modules[m]).lower()}")
    else:
        line("Enable each module? (defaults shown; perception/echo/mundus default off)")
        for m in MODULE_ORDER:
            default_on = DEFAULT_MODULE_SET.get(m, False)
            modules[m] = _ask_yes_no(input_fn, f"  enable {m}?", default=default_on)
    # echo is test infrastructure — always off.
    modules["echo"] = False
    cfg["modules"] = dict(modules)

    # --- Step 5: model / voice / STT discovery ------------------------------
    line()
    line("-" * 70)
    line("Model / voice / STT")
    line("-" * 70)
    discovered: dict[str, Any] = {}
    if not defaults and probe_services is not None:
        try:
            discovered = probe_services() or {}
        except Exception:
            discovered = {}

    shipped_lingua = shipped_config.get("lingua") or {}
    shipped_audition = shipped_config.get("audition") or {}
    shipped_vox = shipped_config.get("vox") or {}

    if modules.get("lingua"):
        models = discovered.get("served_models") or []
        if models:
            line("  Models served: " + ", ".join(str(m) for m in models))
        default_model = str(shipped_lingua.get("model_id", ""))
        if defaults:
            model_id = default_model
        else:
            model_id = _ask(
                input_fn,
                f"  [lingua].model_id [{default_model}]: ",
                default=default_model,
            )
        _set(cfg, "lingua", "model_id", model_id)

    if modules.get("vox"):
        voices = discovered.get("voices") or []
        if voices:
            line("  Chatterbox voices: " + ", ".join(str(v) for v in voices))
        default_voice = str(shipped_vox.get("predefined_voice_id", "")) or (
            str(voices[0]) if voices else ""
        )
        if defaults:
            voice_id = default_voice
        else:
            voice_id = ""
            while not voice_id:
                voice_id = _ask(
                    input_fn,
                    f"  [vox].predefined_voice_id (REQUIRED when vox is on) "
                    f"[{default_voice}]: ",
                    default=default_voice,
                )
                if not voice_id:
                    line("    a voice id is required when vox is enabled.")
        # vox enabled REQUIRES a voice id; if defaults left it blank, disable vox
        # rather than write an unusable config.
        if voice_id:
            _set(cfg, "vox", "predefined_voice_id", voice_id)
        else:
            cfg["modules"]["vox"] = False
            line("    no voice id available; disabling vox.")

    if modules.get("audition"):
        stt_models = discovered.get("stt_models") or []
        if stt_models:
            line("  Speaches STT models: " + ", ".join(str(s) for s in stt_models))
        default_stt = str(shipped_audition.get("stt_model", ""))
        if defaults:
            stt = default_stt
        else:
            stt = _ask(
                input_fn,
                f"  [audition].stt_model [{default_stt}]: ",
                default=default_stt,
            )
        _set(cfg, "audition", "stt_model", stt)

    # --- Step 5b: voice-alignment trainer provisioning (Stage 2 / optional) -
    if not defaults and probe_trainer is not None:
        from kaine.setup.trainer_provisioning import trainer_guidance

        _trainer_provisioning_step(
            cfg,
            input_fn=input_fn,
            line=line,
            host=host,
            probe_trainer=probe_trainer,
            guidance_fn=trainer_guidance,
        )

    # --- Step 6: optional extras (computed; install handled by __main__) ----
    extras = implied_extras(cfg["modules"], shipped_config)

    # --- Step 7: research metrics (opt-in) ----------------------------------
    line()
    line("-" * 70)
    line("Research metrics (opt-in)")
    line("-" * 70)
    line(
        "KAINE can submit NUMERIC METRICS ONLY (never speech, transcripts,\n"
        "memories, or any conversation content) to the project, operator-initiated\n"
        "via `python -m kaine.research`. Nothing is ever transmitted automatically."
    )
    if not defaults and _ask_yes_no(
        input_fn, "Opt in to metrics-only research submission?", default=False
    ):
        _set(cfg, "research_submission", "enabled", True)
        _set(cfg, "research_submission", "tier", "metrics")
        recipient = _ask(
            input_fn,
            "  recipient email [kaine.one@tuta.com]: ",
            default="kaine.one@tuta.com",
        )
        _set(cfg, "research_submission", "recipient", recipient)
        _set(cfg, "transfer", "recipient", recipient)
    else:
        line("Research submission left disabled (the default).")

    # --- Step 8: state encryption (opt-in) ----------------------------------
    line()
    line("-" * 70)
    line("State encryption (opt-in)")
    line("-" * 70)
    line(
        "Optional AES-256-GCM encryption-at-rest for persisted cognitive state.\n"
        "If enabled, the entity refuses to boot unless a 32-byte key is available\n"
        "via the KAINE_STATE_KEY environment variable (fail-closed)."
    )
    if not defaults and _ask_yes_no(
        input_fn, "Enable state encryption at rest?", default=False
    ):
        _set_nested(cfg, "security", "state_encryption", "enabled", True)
        line(
            "  Remember to export KAINE_STATE_KEY (32 raw bytes, or base64/hex of\n"
            "  32 bytes) before booting, or the entity will refuse to start."
        )
    else:
        line("State encryption left disabled (the default).")

    return WizardResult(acknowledged=True, config=cfg, extras=extras)
