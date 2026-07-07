# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Turnkey launch + supervision of the OpenAI-compatible model server.

"clone → install → run" should reach a running organ without a manual server
start, so the model server is promoted from guide-only to a launched service —
the same shape Redis/Qdrant use (an idempotent bootstrap run on consent). The
difference: Redis/Qdrant are docker containers whose restart the daemon handles;
the model server is a **native long-running GPU process** (Unsloth Studio's
``llama-server`` on NVIDIA, the unsloth-core build on AMD), so its lifecycle is
ours to own.

The heavy, non-trivial logic lives here in **testable Python** — binary
discovery, launch-command construction, supervision-mode selection, health
gating, and a ``start``/``status``/``stop`` dispatch (entry:
``python -m kaine.setup.model_server <cmd>``). ``scripts/model-server-bootstrap.sh``
is a thin wrapper over this, mirroring the Redis/Qdrant bootstrap ergonomics. This
keeps the one-bootstrap-command UX while making the logic unit-testable with mocks
(the same Python-core / thin-entry split the extras/deps install already uses),
rather than burying it in untestable shell.

No pretend processes: it launches the server binary that is installed (a real
subprocess / real systemd unit) or fails honestly with install guidance — it
NEVER silently installs the multi-GB server toolchain, and never fakes a launch.
This is **process** supervision of a service, distinct from Spot (which supervises
cognitive **modules** inside the cycle process group); the two do not overlap.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from kaine.setup.organ import ORGAN_GGUF_REPO

# Override env for an explicitly-located server binary (any backend / custom build).
SERVER_BIN_ENV = "KAINE_MODEL_SERVER_BIN"

# Override env naming a LoRA adapter to attach at launch (the served organ's
# `--lora <adapter>` flag). Set by the on-device voice-alignment reload bracket
# (kaine.modules.hypnos.organ_window) when restarting the organ with an accepted
# adapter; absent/empty = serve the base organ unchanged. A real serving flag —
# no merge/requantize step needed.
LORA_ADAPTER_ENV = "KAINE_MODEL_SERVER_LORA"

# The standard self-contained Unsloth Studio llama-server location on a CUDA host
# (``~``-relative — not a personal path). Tried when no override is given.
STUDIO_LLAMA_SERVER = (
    Path.home() / ".unsloth" / "llama.cpp" / "build" / "bin" / "llama-server"
)

# State for the background-process supervision path (pidfile + log). Under the
# repo's state/ tree, mirroring where the cycle/preflight write.
STATE_DIR = Path("state/model-server")
PIDFILE = STATE_DIR / "model-server.pid"
LOGFILE = STATE_DIR / "model-server.log"

# systemd --user unit name for the durable-supervision path.
SYSTEMD_UNIT = "kaine-model-server.service"

# Health-gate budget: poll /v1/models until the alias appears.
HEALTH_TIMEOUT_S = 60.0
HEALTH_POLL_INTERVAL_S = 1.0

# Doc + install guidance shown when the server binary is absent (no silent
# multi-GB install — that principle stands; we launch what's installed).
INSTALL_GUIDE_URL = "https://docs.unsloth.ai/get-started/installing-+-updating"


# --------------------------------------------------------------------------
# Binary discovery
# --------------------------------------------------------------------------


def locate_binary(backend: str, override: Optional[str] = None) -> Optional[Path]:
    """Locate the hardware-appropriate model-server binary.

    Resolution order: an explicit ``override`` (or the ``KAINE_MODEL_SERVER_BIN``
    env var when ``override`` is None) wins; otherwise the known Unsloth Studio
    ``llama-server`` location on a CUDA host; otherwise a ``llama-server`` on PATH
    (the unsloth-core / AMD build typically installs one). Returns the resolved
    Path iff it exists, else None (the caller prints the install guide and fails —
    no silent install)."""
    raw = override if override is not None else os.environ.get(SERVER_BIN_ENV)
    if raw:
        cand = Path(raw)
        return cand if cand.is_file() else None
    if backend == "cuda" and STUDIO_LLAMA_SERVER.is_file():
        return STUDIO_LLAMA_SERVER
    on_path = shutil.which("llama-server")
    if on_path:
        return Path(on_path)
    return None


# --------------------------------------------------------------------------
# Launch command construction
# --------------------------------------------------------------------------


def _port_from_chat_url(chat_url: str) -> int:
    parsed = urlparse(chat_url if "//" in chat_url else "//" + chat_url)
    return int(parsed.port or 11434)


def build_launch_cmd(
    binary: Path,
    *,
    gguf: str,
    alias: str,
    chat_url: str,
    host: str = "127.0.0.1",
    lora_adapter: Optional[str] = None,
) -> list[str]:
    """Build the exact server launch argv.

    ``-m <gguf> --alias <[lingua].model_id> --host 127.0.0.1 --port <from chat_url>
    --jinja --reasoning-budget 0`` — the validated serving flags. The alias is the
    served name the wizard verifies and the organ POSTs to, so it MUST equal
    ``[lingua].model_id``. ``--reasoning-budget 0`` is a best-effort server hint to
    cap hybrid-thinking, but on the abliterated Qwen3.5 template it does NOT
    reliably suppress the chain-of-thought (the model reasons first and the
    visible ``content`` comes back empty). Actual suppression is enforced
    per-request, client-side, via ``chat_template_kwargs.enable_thinking=false``
    (kaine.modules.lingua.client) — the organ is a voice, not a reasoner.

    When ``lora_adapter`` is given (the on-device voice-alignment reload bracket
    passes an accepted adapter via ``LORA_ADAPTER_ENV``), ``--lora <adapter>`` is
    appended so the served organ carries the trained voice — a real serving flag,
    no merge/requantize step."""
    port = _port_from_chat_url(chat_url)
    cmd = [
        str(binary),
        "-m", str(gguf),
        "--alias", alias,
        "--host", host,
        "--port", str(port),
        "--jinja",
        "--reasoning-budget", "0",
    ]
    if lora_adapter:
        cmd += ["--lora", str(lora_adapter)]
    return cmd


# --------------------------------------------------------------------------
# Supervision-mode selection
# --------------------------------------------------------------------------


def systemd_user_available(runner: Any = None) -> bool:
    """True iff ``systemctl --user`` works on this host (durable-supervision path).

    A real probe — runs ``systemctl --user is-system-running`` (any exit is fine;
    we only need the command to be launchable against a user manager). Never
    raises; returns False when systemd-user is unavailable (no systemd, no user
    bus, containers)."""
    if shutil.which("systemctl") is None:
        return False
    run = runner if runner is not None else subprocess.run
    try:
        proc = run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except Exception:
        return False
    # is-system-running prints running/degraded/... and exits 0/non-0; a usable
    # user manager answers at all. "Failed to connect to bus" (no user bus) goes
    # to stderr with a non-zero exit and an empty stdout → treat as unavailable.
    out = (getattr(proc, "stdout", "") or "").strip()
    return bool(out)


def choose_supervision(runner: Any = None) -> str:
    """Pick the supervision mode: ``"systemd"`` where systemd-user works, else
    ``"background"`` (a supervised background process + pidfile)."""
    return "systemd" if systemd_user_available(runner=runner) else "background"


# --------------------------------------------------------------------------
# Health gate
# --------------------------------------------------------------------------


def health_check(
    chat_url: str,
    alias: str,
    *,
    api_key: Optional[str] = None,
    timeout_s: float = HEALTH_TIMEOUT_S,
    poll_interval_s: float = HEALTH_POLL_INTERVAL_S,
    now: Any = None,
    sleep: Any = None,
    probe: Any = None,
) -> tuple[bool, str]:
    """Poll ``{chat_url}/models`` until ``alias`` is listed or the budget elapses.

    Reuses :func:`kaine.setup.organ.verify_served_alias` for the actual probe.
    Returns ``(ok, detail)``. Never raises. ``now``/``sleep``/``probe`` are
    injectable for tests (no real clock/network in the suite)."""
    from kaine.setup.organ import verify_served_alias

    _now = now if now is not None else time.monotonic
    _sleep = sleep if sleep is not None else time.sleep
    _probe = probe if probe is not None else verify_served_alias

    deadline = _now() + timeout_s
    last = "no probe attempted"
    while True:
        result = _probe(chat_url, alias, api_key=api_key)
        if result.listed:
            return True, result.detail
        last = result.detail
        if _now() >= deadline:
            return False, (
                f"model server did not list '{alias}' within {timeout_s:.0f}s "
                f"({last})"
            )
        _sleep(poll_interval_s)


# --------------------------------------------------------------------------
# systemd --user unit text
# --------------------------------------------------------------------------


def render_systemd_unit(launch_cmd: list[str]) -> str:
    """Render a ``Restart=on-failure`` user unit for durable supervision."""
    exec_start = " ".join(launch_cmd)
    return (
        "[Unit]\n"
        "Description=KAINE OpenAI-compatible model server (language organ)\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemd_unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / SYSTEMD_UNIT


# --------------------------------------------------------------------------
# start / status / stop dispatch
# --------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pidfile(pidfile: Path) -> Optional[int]:
    try:
        return int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return None


def _resolve_launch(
    config: dict[str, Any], *, override_bin: Optional[str]
) -> tuple[Optional[Path], list[str], str, str, Optional[str]]:
    """Resolve (binary, launch_cmd, chat_url, alias, api_key) from config.

    ``binary`` is None when no server binary is found. The GGUF path is the
    published organ repo id served by name — llama-server resolves the local
    snapshot from the HF cache, so the repo id is a valid ``-m`` target on a
    host that downloaded it; an operator override may point ``-m`` at a file."""
    from kaine.setup.organ import detect_organ_backend

    lingua = config.get("lingua") or {}
    chat_url = str(lingua.get("chat_url", "http://127.0.0.1:11434/v1"))
    alias = str(lingua.get("model_id", ORGAN_GGUF_REPO))
    api_key = lingua.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY")

    backend = detect_organ_backend().backend
    binary = locate_binary(backend, override=override_bin)
    if binary is None:
        return None, [], chat_url, alias, api_key

    # The GGUF to serve is a real FILE PATH (llama-server's -m is a path, not a repo
    # id): an explicit operator override, else the deterministic local file the
    # consented download step wrote.
    from kaine.setup.organ import served_gguf_path

    # Resolve to an ABSOLUTE path before handing it to the server: under
    # `systemd --user` the working directory is $HOME (not the repo), so the
    # repo-relative default from served_gguf_path() would make `-m state/models/…`
    # fail to open. resolve() also follows an operator symlink to wherever the
    # local build actually lives.
    gguf = str(Path(lingua.get("model_gguf_path") or served_gguf_path()).resolve())
    # An accepted voice-alignment adapter to attach at launch (--lora), set by the
    # on-device reload bracket; absent = serve the base organ unchanged.
    lora_adapter = os.environ.get(LORA_ADAPTER_ENV) or None
    cmd = build_launch_cmd(
        binary, gguf=gguf, alias=alias, chat_url=chat_url, lora_adapter=lora_adapter
    )
    return binary, cmd, chat_url, alias, api_key


def _load_config() -> dict[str, Any]:
    from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, load_kaine_config

    try:
        return load_kaine_config(SHIPPED_CONFIG_PATH, OPERATOR_CONFIG_PATH)
    except Exception:
        return {}


def _install_guide(out: Any) -> None:
    out(
        "Model-server binary not found. Install the hardware-appropriate server "
        "(Unsloth Studio's llama-server on NVIDIA, the unsloth-core build on AMD) "
        f"per {INSTALL_GUIDE_URL}, or set {SERVER_BIN_ENV} to its path. The "
        "bootstrap NEVER silently installs the multi-GB toolchain.\n"
    )


def cmd_start(
    config: Optional[dict[str, Any]] = None,
    *,
    override_bin: Optional[str] = None,
    out: Any = None,
    runner: Any = None,
    supervision: Optional[str] = None,
) -> int:
    """Launch + supervise the model server; health-gate on the served alias.

    Returns 0 on a healthy launch, non-zero otherwise (binary absent, launch
    failed, or the alias never appeared). Idempotent: if the server is already
    listing the alias it reports up and returns 0 without relaunching."""
    cfg = config if config is not None else _load_config()
    emit = out if out is not None else sys.stdout.write
    run = runner if runner is not None else subprocess.run

    binary, cmd, chat_url, alias, api_key = _resolve_launch(
        cfg, override_bin=override_bin
    )
    if binary is None:
        _install_guide(emit)
        return 2

    # The GGUF to serve must be a real file (llama-server -m is a path). If the
    # consented download step has not run, fail honestly with guidance rather than
    # launching the server against a missing file.
    gguf_path = cmd[cmd.index("-m") + 1]
    if not Path(gguf_path).is_file():
        emit(
            f"organ GGUF not found at {gguf_path}. Run the wizard's organ-download "
            "step (or `hf download "
            f"{ORGAN_GGUF_REPO} {Path(gguf_path).name} --local-dir "
            f"{Path(gguf_path).parent}`) before starting the server. The bootstrap "
            "never fakes a launch.\n"
        )
        return 5

    # Idempotent: already serving the alias? report and stop.
    from kaine.setup.organ import verify_served_alias

    pre = verify_served_alias(chat_url, alias, api_key=api_key)
    if pre.listed:
        emit(f"model server already up — {pre.detail}\n")
        return 0

    mode = supervision or choose_supervision(runner=run)
    emit(f"launching model server ({mode}): {' '.join(cmd)}\n")

    if mode == "systemd":
        ok = _start_systemd(cmd, run=run, emit=emit)
    else:
        ok = _start_background(cmd, emit=emit)
    if not ok:
        return 3

    healthy, detail = health_check(chat_url, alias, api_key=api_key)
    if healthy:
        emit(f"model server healthy — {detail}\n")
        return 0
    emit(f"model server launched but unhealthy — {detail}\n")
    return 4


def _start_systemd(cmd: list[str], *, run: Any, emit: Any) -> bool:
    unit_path = _systemd_unit_path()
    try:
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(render_systemd_unit(cmd))
        run(["systemctl", "--user", "daemon-reload"], check=True)
        run(["systemctl", "--user", "enable", "--now", SYSTEMD_UNIT], check=True)
        return True
    except Exception as exc:
        emit(f"systemd --user launch failed ({exc}); try the background path.\n")
        return False


def _start_background(cmd: list[str], *, emit: Any) -> bool:
    existing = _read_pidfile(PIDFILE)
    if existing and _pid_alive(existing):
        emit(f"model server already running (pid {existing}).\n")
        return True
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Popen dup()s this fd into the launched server, which keeps its own
        # copy for the life of the process. The parent only needs it open across
        # the Popen call, so scope it to a context manager: the child inherits a
        # live log fd while the parent's copy is closed as soon as Popen returns
        # (no leaked file handle).
        with open(LOGFILE, "ab") as log:
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        PIDFILE.write_text(str(proc.pid))
        emit(f"model server started (pid {proc.pid}; log {LOGFILE}).\n")
        return True
    except Exception as exc:
        emit(f"background launch failed ({exc}).\n")
        return False


def cmd_status(
    config: Optional[dict[str, Any]] = None,
    *,
    out: Any = None,
    runner: Any = None,
) -> int:
    """Report whether the server is up and lists the configured alias.

    Returns 0 if the alias is served, non-zero otherwise."""
    cfg = config if config is not None else _load_config()
    emit = out if out is not None else sys.stdout.write

    lingua = cfg.get("lingua") or {}
    chat_url = str(lingua.get("chat_url", "http://127.0.0.1:11434/v1"))
    alias = str(lingua.get("model_id", ORGAN_GGUF_REPO))
    api_key = lingua.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY")

    from kaine.setup.organ import verify_served_alias

    result = verify_served_alias(chat_url, alias, api_key=api_key)
    port = _port_from_chat_url(chat_url)
    if result.listed:
        emit(f"[up]   model server on port {port} — {result.detail}\n")
        return 0
    emit(f"[down] model server on port {port} — {result.detail}\n")
    return 1


def cmd_stop(
    config: Optional[dict[str, Any]] = None,
    *,
    out: Any = None,
    runner: Any = None,
) -> int:
    """Stop the supervised server (systemd unit or the background process)."""
    emit = out if out is not None else sys.stdout.write
    run = runner if runner is not None else subprocess.run

    stopped = False
    # systemd path (best-effort; ignore if the unit is not installed).
    if shutil.which("systemctl") and _systemd_unit_path().is_file():
        try:
            run(["systemctl", "--user", "disable", "--now", SYSTEMD_UNIT], check=False)
            emit(f"stopped systemd unit {SYSTEMD_UNIT}.\n")
            stopped = True
        except Exception as exc:
            emit(f"could not stop systemd unit ({exc}).\n")

    # Background-process path.
    pid = _read_pidfile(PIDFILE)
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, 15)  # SIGTERM
            emit(f"sent SIGTERM to model server (pid {pid}).\n")
            stopped = True
        except Exception as exc:
            emit(f"could not signal pid {pid} ({exc}).\n")
    try:
        if PIDFILE.exists():
            PIDFILE.unlink()
    except OSError:
        pass

    if not stopped:
        emit("no supervised model server found to stop.\n")
        return 1
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.model_server",
        description=(
            "Launch + supervise the OpenAI-compatible model server (language "
            "organ). NEVER silently installs the server toolchain."
        ),
    )
    parser.add_argument(
        "command", choices=("start", "status", "stop"), help="lifecycle action"
    )
    parser.add_argument(
        "--bin",
        default=None,
        help=f"explicit server binary path (else {SERVER_BIN_ENV} / auto-detect)",
    )
    args = parser.parse_args(argv)

    if args.command == "start":
        return cmd_start(override_bin=args.bin)
    if args.command == "status":
        return cmd_status()
    return cmd_stop()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
