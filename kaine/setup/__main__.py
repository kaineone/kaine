# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Entrypoint for the first-run wizard: ``python -m kaine.setup``.

Wires the real input, host scan, service probes, operator-config write, optional
extras install, and the next-steps summary around the pure step logic in
:mod:`kaine.setup.wizard`. It never boots the entity and never writes the shipped
``config/kaine.toml``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, load_kaine_config
from kaine.setup import tomlwriter
from kaine.setup.wizard import WizardResult, run_wizard

DEFAULT_OPERATOR_PATH = OPERATOR_CONFIG_PATH


def _describe_host_with_cpu() -> dict[str, Any]:
    """describe_host() augmented with a cpu_count key for the wizard display."""
    from kaine.hardware import describe_host

    host = describe_host()
    host["cpu_count"] = os.cpu_count()
    return host


def probe_services(*, timeout_s: float = 2.0) -> dict[str, Any]:
    """Best-effort discovery of served models / voices / STT models.

    Fully guarded — any unreachable or erroring service simply contributes no
    options. Returns ``{"served_models": [...], "voices": [...],
    "stt_models": [...]}``.
    """
    result: dict[str, Any] = {"served_models": [], "voices": [], "stt_models": []}
    try:
        import httpx
    except Exception:
        return result

    # Model server (Unsloth Studio / llama.cpp): OpenAI-compatible
    # /v1/models -> {"data": [{"id": "..."}, ...]}.
    try:
        resp = httpx.get("http://127.0.0.1:11434/v1/models", timeout=timeout_s)
        if resp.status_code == 200:
            data = resp.json()
            result["served_models"] = [
                str(m.get("id"))
                for m in (data.get("data") or [])
                if m.get("id")
            ]
    except Exception:
        # Best-effort, optional probe: the model server may not be running.
        # Failures are intentionally ignored so setup continues empty.
        pass

    # Chatterbox: /get_predefined_voices -> list or dict of voice ids
    try:
        resp = httpx.get(
            "http://127.0.0.1:8883/get_predefined_voices", timeout=timeout_s
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                voices = [str(v) for v in data]
            elif isinstance(data, dict):
                voices = [str(v) for v in data.keys()]
            else:
                voices = []
            result["voices"] = voices
    except Exception:
        # Best-effort, optional probe: Chatterbox may not be running. Failures
        # are intentionally ignored so setup continues with voices empty.
        pass

    # Speaches: /v1/models -> {"data": [{"id": "..."}, ...]}
    try:
        resp = httpx.get("http://127.0.0.1:8000/v1/models", timeout=timeout_s)
        if resp.status_code == 200:
            data = resp.json()
            result["stt_models"] = [
                str(m.get("id")) for m in (data.get("data") or []) if m.get("id")
            ]
    except Exception:
        # Best-effort, optional probe: Speaches may not be running. Failures are
        # intentionally ignored so setup continues with stt_models empty.
        pass

    return result


def _probe_trainer(
    interpreter: Any, *, backend: str = "cuda"
) -> tuple[bool, str]:
    """Real probe for a usable external voice-alignment trainer interpreter.

    Thin wrapper over :func:`kaine.setup.trainer_provisioning.probe_trainer` so
    the wizard step stays pure (the probe runs a subprocess; the wizard does not).
    """
    from kaine.setup.trainer_provisioning import probe_trainer

    return probe_trainer(interpreter, backend=backend)


def _install_extras(
    extras: list[str],
    *,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    defaults: bool,
) -> None:
    """Offer to ``pip install -e .[<extra>]`` the implied extras (confirmed)."""
    if not extras:
        return
    if defaults:
        out(
            "[--defaults] Skipping extras install. Implied extras: "
            + ", ".join(extras)
            + "\n"
        )
        return
    extras_spec = ",".join(sorted(set(extras)))
    cmd = [".venv/bin/pip", "install", "-e", f".[{extras_spec}]"]
    out("\nYour module choices imply these optional extras: " + extras_spec + "\n")
    out("  command: " + " ".join(cmd) + "\n")
    raw = input_fn("Run it now? [y/N]: ").strip().lower()
    if raw not in ("y", "yes"):
        out("  Skipped. Install later with: " + " ".join(cmd) + "\n")
        return
    try:
        subprocess.run(cmd, check=True)
        out("  extras installed.\n")
    except Exception as exc:  # never crash the wizard on an install failure
        out(f"  extras install failed ({exc}); run manually: " + " ".join(cmd) + "\n")


def _provision_organ(
    config: dict[str, Any],
    *,
    shipped: dict[str, Any],
    host: dict[str, Any],
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    defaults: bool,
) -> None:
    """Consented, hardware-aware download of the published organ, then launch.

    Fires ONLY when lingua is enabled ("where appropriate"). Mirrors
    :func:`_install_extras` orchestration: show the plan + bytes, run a REAL
    download on explicit consent (never a faked/no-op success), then offer the
    turnkey server bootstrap launch and verify the served alias. On decline it
    prints acquisition guidance and downloads nothing. Never crashes the wizard.
    """
    from kaine.setup import organ as organ_mod

    modules = config.get("modules") or {}
    if not modules.get("lingua"):
        return  # organ not needed; no step offered

    # The resolved config for the Stage-2 (safetensors) decision: the operator's
    # module choices over the shipped defaults (so [hypnos.voice_alignment].enabled
    # is read from the shipped file unless the operator overrode it).
    resolved = dict(shipped)
    resolved["modules"] = dict(modules)
    if config.get("hypnos"):
        resolved["hypnos"] = {
            **(shipped.get("hypnos") or {}),
            **(config.get("hypnos") or {}),
        }
    # The served alias the operator chose (or the shipped default).
    lingua_cfg = {**(shipped.get("lingua") or {}), **(config.get("lingua") or {})}
    chat_url = str(lingua_cfg.get("chat_url", "http://127.0.0.1:11434/v1"))
    model_id = str(lingua_cfg.get("model_id", organ_mod.ORGAN_GGUF_REPO))
    api_key = lingua_cfg.get("api_key") or os.environ.get(
        "KAINE_MODEL_SERVER_API_KEY"
    )

    out("\n" + "-" * 70 + "\n")
    out("Language organ download + serve\n")
    out("-" * 70 + "\n")

    try:
        backend = organ_mod.detect_organ_backend(str(host.get("backend") or "cpu"))
        plan = organ_mod.plan_organ_download(modules, backend, config=resolved)
    except Exception as exc:  # never crash the wizard on a planning error
        out(f"  organ step skipped (planning error: {exc}).\n")
        return

    out(f"  {backend.summary}\n")
    if not plan.needed or not plan.artifacts:
        out("  No organ download needed for this configuration.\n")
        return

    out(f"  Will download (~{plan.total_size_gb:.0f} GB total):\n")
    for art in plan.artifacts:
        out(
            f"    - {art.fmt}: {art.repo} (~{art.size_gb:.0f} GB; {art.reason})\n"
        )
        out(f"        command: {' '.join(art.command)}\n")

    if not backend.available:
        # No supported accelerator toolchain — guide, do not install silently.
        for ln in organ_mod.acquisition_guide(backend, plan):
            out(ln + "\n")
        return

    if defaults:
        out("  [--defaults] organ not downloaded; run the command(s) above.\n")
        return

    raw = input_fn("  Download the published organ now? [y/N]: ").strip().lower()
    if raw not in ("y", "yes"):
        out("  Skipped. Acquisition guidance:\n")
        for ln in organ_mod.acquisition_guide(backend, plan):
            out(ln + "\n")
        return

    try:
        results = organ_mod.run_organ_download(plan, consent=True)
    except Exception as exc:  # defensive — run_organ_download already catches
        out(f"  organ download error ({exc}).\n")
        return
    all_ok = bool(results) and all(r.ok for r in results)
    for r in results:
        tag = "ok" if r.ok else "FAILED"
        out(f"    [{tag}] {r.repo} — {r.detail}\n")
    if not all_ok:
        out("  Organ not fully downloaded; serve step skipped until it succeeds.\n")
        return
    # Record the resolved revision(s) for run-manifest provenance (best-effort).
    state_written = organ_mod.write_revision_state(results)
    if state_written:
        out(f"  Recorded organ revision(s) for provenance: {state_written}\n")

    # Turnkey: offer to launch + supervise the server, then verify the alias.
    launch = input_fn(
        "  Launch + supervise the model server now? [y/N]: "
    ).strip().lower()
    if launch not in ("y", "yes"):
        out(
            "  Skipped. Start it later: bash scripts/model-server-bootstrap.sh start\n"
        )
        return
    cmd = "bash scripts/model-server-bootstrap.sh start"
    out(f"  command: {cmd}\n")
    try:
        subprocess.run(cmd, shell=True, check=True)
    except Exception as exc:  # never crash the wizard on a launch failure
        out(f"  model server launch failed ({exc}); run manually: {cmd}\n")
        return

    # Verify the served alias matches [lingua].model_id (catch the 404 pre-boot).
    try:
        verdict = organ_mod.verify_served_alias(chat_url, model_id, api_key=api_key)
    except Exception as exc:
        out(f"  served-name verify skipped (probe error: {exc}).\n")
        return
    if verdict.listed:
        out(f"  served-name OK — {verdict.detail}\n")
    else:
        out(
            "  ACTION NEEDED — served name mismatch (not a boot-time 404):\n"
            f"    {verdict.detail}\n"
        )


def _provision_dependencies(
    config: dict[str, Any],
    *,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    defaults: bool,
) -> None:
    """Detect the external services the enabled modules need; offer a consented,
    shown install for runnable ones (Redis/Qdrant bootstrap scripts, the model
    server bootstrap script) and print real setup guidance for the heavy GPU
    services. Never installs without explicit consent; never crashes the
    wizard; never pretends a guide-only service was installed."""
    from kaine.setup.dependencies import detect_dependencies

    modules = config.get("modules") or {}
    redis_port = (config.get("redis") or {}).get("port")
    statuses = detect_dependencies(modules, redis_port=redis_port)
    if not statuses:
        return

    out("\n" + "-" * 70 + "\n")
    out("External service dependencies\n")
    out("-" * 70 + "\n")
    for st in statuses:
        spec = st.spec
        # The model server is launched by the dedicated organ step (download →
        # launch → verify); don't prompt for the same bootstrap twice in one run.
        if spec.name == "model_server" and not st.running:
            out(
                f"  [organ]   {spec.name} ({spec.role}) — launched by the organ "
                "step above (or: bash scripts/model-server-bootstrap.sh start)\n"
            )
            continue
        if st.running:
            out(f"  [up]      {spec.name} ({spec.role}) — already running\n")
            continue
        if spec.kind == "guide":
            out(f"  [missing] {spec.name} ({spec.role}) — {spec.note}\n")
            if spec.guide_url:
                out(f"            docs: {spec.guide_url}\n")
            for step in spec.guide_steps:
                out(f"            - {step}\n")
            continue
        # kind == "command": show the exact command, run ONLY on explicit consent.
        out(f"  [missing] {spec.name} ({spec.role})\n")
        if spec.note:
            out(f"            {spec.note}\n")
        out(f"            command: {spec.command}\n")
        if defaults:
            out("            [--defaults] not run; run the command above to provision.\n")
            continue
        raw = input_fn(f"  Run it now to start {spec.name}? [y/N]: ").strip().lower()
        if raw not in ("y", "yes"):
            out(f"            Skipped. Run later: {spec.command}\n")
            continue
        try:
            subprocess.run(spec.command, shell=True, check=True)
            out(f"            {spec.name} provisioning command completed.\n")
        except Exception as exc:  # never crash the wizard on a provisioning failure
            out(
                f"            {spec.name} provisioning failed ({exc}); "
                f"run manually: {spec.command}\n"
            )


def _print_next_steps(
    config: dict[str, Any],
    *,
    operator_path: Path,
    out: Callable[[str], Any],
) -> None:
    modules = config.get("modules") or {}
    enc_enabled = bool(
        ((config.get("security") or {}).get("state_encryption") or {}).get("enabled")
    )

    def line(text: str = "") -> None:
        out(text + "\n")

    line()
    line("=" * 70)
    line("Setup complete")
    line("=" * 70)
    line(f"Wrote operator overrides to: {operator_path}")
    line("(gitignored; the shipped config/kaine.toml is untouched and all-off.)")

    line()
    line("Environment gates you will need:")
    line("  KAINE_CYCLE_OPERATOR_PRESENT=1        (required to launch the cycle)")
    line("  KAINE_FIRST_BOOT_OPERATOR_PRESENT=1   (required by scripts/first-boot.sh)")
    if (config.get("hypnos") or {}).get("voice_alignment") and modules.get("hypnos"):
        line("  KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1  (if voice-alignment training)")
    if modules.get("mundus"):
        line("  KAINE_MUNDUS_OPERATOR_APPROVED=1      (required when mundus is enabled)")
    if enc_enabled:
        line("  KAINE_STATE_KEY=<32-byte key>         (required: encryption is enabled)")

    line()
    line("Bring up the supporting services you enabled:")
    line("  bash scripts/redis-bootstrap.sh       # event bus")
    if modules.get("mnemos") or modules.get("empatheia"):
        line("  bash scripts/qdrant-bootstrap.sh      # vector memory")
    if modules.get("lingua"):
        line("  bash scripts/model-server-bootstrap.sh start   # language organ")
    if modules.get("audition"):
        line("  start Speaches (STT) on CPU with medium.en")
    if modules.get("vox"):
        line("  start Chatterbox (TTS)")

    line()
    line("Then launch (two terminals):")
    line("  python -m kaine.nexus                          # dashboard")
    line("  KAINE_CYCLE_OPERATOR_PRESENT=1 python -m kaine.cycle   # the entity")
    line()
    line("Recommended first: KAINE_FIRST_BOOT_OPERATOR_PRESENT=1 scripts/first-boot.sh")


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    out: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup",
        description="KAINE first-run setup wizard.",
    )
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="non-interactive: minimal safe modules, all-CPU, no metrics, no encryption",
    )
    parser.add_argument(
        "--operator-path",
        type=Path,
        default=DEFAULT_OPERATOR_PATH,
        help="where to write the operator override (default: config/kaine.operator.toml)",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=SHIPPED_CONFIG_PATH,
        help="path to the shipped config to read defaults from",
    )
    args = parser.parse_args(argv)

    sink: TextIO = out or sys.stdout
    _input: Callable[[str], str] = input_fn or input

    def write(text: str) -> None:
        sink.write(text)

    # Load the shipped config (for capture flags / backends / default ids).
    try:
        shipped = load_kaine_config(args.config_path, operator_path=Path("/nonexistent"))
    except FileNotFoundError:
        write(f"shipped config not found at {args.config_path}\n")
        return 2

    host = _describe_host_with_cpu()

    result: WizardResult = run_wizard(
        input_fn=_input,
        out=write,
        host=host,
        shipped_config=shipped,
        probe_services=(None if args.defaults else probe_services),
        probe_trainer=(None if args.defaults else _probe_trainer),
        defaults=args.defaults,
    )

    if not result.acknowledged:
        return 1

    # Write the operator override.
    operator_path: Path = args.operator_path
    operator_path.parent.mkdir(parents=True, exist_ok=True)
    operator_path.write_text(tomlwriter.dumps(result.config))

    # Offer the implied extras install.
    _install_extras(
        result.extras, input_fn=_input, out=write, defaults=args.defaults
    )

    # Consented, hardware-aware organ download + turnkey serve (lingua only).
    _provision_organ(
        result.config,
        shipped=shipped,
        host=host,
        input_fn=_input,
        out=write,
        defaults=args.defaults,
    )

    # Detect + offer-or-guide the external services the enabled modules need.
    _provision_dependencies(
        result.config, input_fn=_input, out=write, defaults=args.defaults
    )

    _print_next_steps(result.config, operator_path=operator_path, out=write)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
