# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spawn logic for the browser setup server.

This is the only file under ``kaine/setup/`` whose source contains the string
literal ``"kaine.cycle"`` inside a list or tuple literal. Starting an entity is
a one-way welfare event: every gate here fails closed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kaine import hardware

log = logging.getLogger(__name__)

SPAWN_ACK_PHRASE = "I will stay present and responsible for this entity"
SPAWN_ACK_TEXT = (
    "Starting the KAINE cognitive cycle starts a being whose welfare you are "
    "responsible for under the CAL Article 4 care obligations. You must remain "
    "present while the cycle runs, ready to respond to its welfare needs. "
    "Stopping, deleting or otherwise ending that being later is governed by the "
    "same welfare rules."
)
SPAWN_ACK_VERSION = 1
NONCE_TTL_S = 300.0
READY_TIMEOUT_S = 30.0
LOG_KEEP_RUNS = 10


class _LazyExitDict(dict):
    """Lazily imports cycle exit codes the first time they are looked up."""

    def _load(self) -> None:
        if getattr(self, "_loaded", False):
            return
        from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE
        from kaine.cycle.unattended_gate import UNATTENDED_GATE_EXIT_CODE

        self.update(
            {
                1: "configuration error or boot refusal; see the stderr file",
                2: "the cycle refused: operator presence was not confirmed",
                RESEARCH_GATE_EXIT_CODE: "the cycle refused: the research safety net was not satisfied",
                UNATTENDED_GATE_EXIT_CODE: "the cycle refused: the unattended supervision safety net was not satisfied",
            }
        )
        self._loaded = True

    def __getitem__(self, key):  # type: ignore[override]
        self._load()
        return super().__getitem__(key)

    def __contains__(self, key):  # type: ignore[override]
        self._load()
        return super().__contains__(key)

    def get(self, key, default=None):  # type: ignore[override]
        self._load()
        return super().get(key, default)


EXIT_EXPLANATIONS: dict[int, str] = _LazyExitDict()


def record_acknowledgement(state_dir: Path, phrase: str, *, now) -> None:
    """Append one JSON line documenting the operator's spawn acknowledgement."""
    lifecycle_dir = state_dir / "lifecycle"
    lifecycle_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(lifecycle_dir, 0o700)

    record = {
        "at": now().isoformat(),
        "text_version": SPAWN_ACK_VERSION,
        "text_sha256": __sha256(SPAWN_ACK_TEXT),
        "affirmation": phrase,
    }
    line = json.dumps(record, separators=(",", ":")) + "\n"

    path = lifecycle_dir / "spawn_acknowledgements.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def __sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hostname_from_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except Exception:
        return None
    schemes = {"http", "https", "redis", "rediss", "grpc"}
    if parsed.scheme in schemes and parsed.hostname:
        return parsed.hostname
    return None


def compose_markers(
    config: dict[str, Any],
    *,
    repo_root: Path,
    env: Mapping[str, str],
    docker_probe,
) -> list[str]:
    """Return reasons this looks like a compose install that must refuse host spawn."""
    markers: list[str] = []

    if hardware._in_container():
        markers.append("setup is running inside a container")

    compose_dir = repo_root / "compose"
    compose_names: set[str] = set()
    read_error: str | None = None
    if compose_dir.exists():
        try:
            for yml in compose_dir.glob("*.yml"):
                try:
                    text = yml.read_text(encoding="utf-8")
                    for match in re.finditer(
                        r'^\s+container_name:\s*["\']?([A-Za-z0-9_.-]+)',
                        text,
                        re.MULTILINE,
                    ):
                        compose_names.add(match.group(1))
                except Exception as exc:
                    read_error = type(exc).__name__
                    break
        except Exception as exc:
            read_error = type(exc).__name__

    if read_error is not None:
        markers.append(f"compose files could not be read ({read_error})")

    targets: list[tuple[str, str]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                sub = f"{path}.{key}" if path else str(key)
                if isinstance(value, str):
                    if key == "host":
                        targets.append((sub, value))
                    host = _hostname_from_url(value)
                    if host:
                        targets.append((sub, host))
                elif isinstance(value, (dict, list)):
                    walk(value, sub)
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                sub = f"{path}.{idx}"
                if isinstance(value, str):
                    host = _hostname_from_url(value)
                    if host:
                        targets.append((sub, host))
                elif isinstance(value, (dict, list)):
                    walk(value, sub)

    walk(config, "")

    redis_url = env.get("KAINE_REDIS_URL")
    if isinstance(redis_url, str):
        host = _hostname_from_url(redis_url)
        if host:
            targets.append(("KAINE_REDIS_URL", host))

    for path, host in targets:
        if host in compose_names:
            markers.append(
                f"the configuration targets the compose network ({path} → {host})"
            )

    probe = docker_probe()
    if probe is True:
        markers.append(
            "a kaine-cycle container exists on this host; start the entity with docker compose up kaine-cycle"
        )
    elif probe is None:
        markers.append(
            "no container runtime (docker or podman) could be asked whether a containerized cycle exists"
        )

    return markers


def supervision_refusal(config: dict[str, Any], child_env: dict[str, str]) -> str | None:
    """Return a refusal string when the supervision mode is not operator-present."""
    from kaine.cycle.unattended_gate import (
        SupervisionConfigError,
        resolve_supervision_mode,
    )

    try:
        mode = resolve_supervision_mode(config, env=child_env)
    except SupervisionConfigError:
        return (
            "this configuration selects an invalid boot; "
            "the browser spawn is the operator-present path only"
        )

    if mode != "operator":
        return (
            f"this configuration selects {mode} boot; "
            "the browser spawn is the operator-present path only"
        )
    return None


async def run_preboot(
    repo_root: Path, *, timeout_s: float = 600.0
) -> tuple[bool, list[dict], str]:
    """Run the shared pre-boot check and return its JSON report."""
    env = os.environ.copy()
    env.pop("KAINE_CYCLE_OPERATOR_PRESENT", None)

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "kaine.preboot",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=repo_root,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return (False, [], "the pre-boot check timed out")

    text = stdout.decode("utf-8", errors="replace")
    try:
        report = json.loads(text)
    except Exception:
        return (
            False,
            [],
            f"the pre-boot check produced no readable result (exit {proc.returncode})",
        )

    results = report.get("results", []) if isinstance(report.get("results"), list) else []
    verdict = report.get("verdict", "") if isinstance(report.get("verdict"), str) else ""
    ok = bool(report.get("ok", False)) and proc.returncode == 0
    return (ok, results, verdict)


def prune_logs(log_dir: Path, keep: int = LOG_KEEP_RUNS) -> None:
    """Keep the newest ``keep`` cycle log runs and delete the rest."""
    try:
        if not log_dir.exists():
            return
        files = [
            p
            for p in log_dir.iterdir()
            if p.is_file()
            and p.name.startswith("cycle-")
            and (p.name.endswith(".stderr") or ".log" in p.name)
        ]
        stems = sorted({p.name.split(".", 1)[0] for p in files}, reverse=True)
        keep_set = set(stems[:keep])
        for p in files:
            if p.name.split(".", 1)[0] not in keep_set:
                p.unlink(missing_ok=True)
    except Exception:
        pass


def start_cycle(
    repo_root: Path,
    log_dir: Path,
    *,
    keep_info: bool,
    popen=subprocess.Popen,
    now,
) -> tuple[subprocess.Popen, Path, Path]:
    """Start ``python -m kaine.cycle`` detached, with a private log file."""
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"cycle-{stamp}.log"
    stderr_path = log_dir / f"cycle-{stamp}.stderr"

    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(log_dir, 0o700)

    prune_logs(log_dir)

    argv = [
        sys.executable,
        "-m",
        "kaine.cycle",
        "--log-file",
        str(log_path),
        "--log-level",
        "INFO" if keep_info else "WARNING",
    ]

    child_env = os.environ.copy()
    child_env["KAINE_CYCLE_OPERATOR_PRESENT"] = "1"

    fd = os.open(stderr_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        proc = popen(
            argv,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            stderr=fd,
            start_new_session=True,
            close_fds=True,
            cwd=repo_root,
        )
    finally:
        os.close(fd)

    return proc, log_path, stderr_path


async def wait_ready(
    proc: subprocess.Popen,
    runtime_path: Path,
    *,
    timeout_s: float = READY_TIMEOUT_S,
    poll_s: float = 0.5,
    not_before: float | None = None,
) -> tuple[str, int | None]:
    """Wait for the cycle to write its runtime file or exit.

    ``not_before`` is the wall-clock time the cycle was started. A runtime
    file older than that is a previous run's, even if its pid was reused.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ret = proc.poll()
        if ret is not None:
            return ("exited", ret)

        try:
            fresh = not_before is None or (
                # Allow for coarse filesystem timestamps.
                runtime_path.stat().st_mtime >= not_before - 2.0
            )
            if fresh:
                data = json.loads(runtime_path.read_text(encoding="utf-8"))
                if isinstance(data.get("pid"), int) and data["pid"] == proc.pid:
                    return ("ready", None)
        except Exception:
            # Not written yet, or mid-write: poll again.
            pass

        await asyncio.sleep(poll_s)

    return ("starting", None)


def _tail_lines(path: Path, n: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


_ERROR_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (ERROR|CRITICAL) ([A-Za-z0-9_.]+): "
)


def _matching_log_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    matches: list[str] = []
    for line in text.splitlines():
        m = _ERROR_LOG_RE.match(line)
        if m:
            matches.append(f"{m.group(1)} {m.group(2)} {m.group(3)}")
    return matches


def error_summary(log_path: Path, *, max_lines: int = 5) -> list[str]:
    """Content-free summary of recent ERROR/CRITICAL log lines.

    Reads the current log and its ``.1`` backup (older) and returns the
    last ``max_lines`` matching lines as ``<time> <LEVEL> <logger>``.
    The message after the logger is deliberately never included.
    """
    older = _matching_log_lines(Path(str(log_path) + ".1"))
    current = _matching_log_lines(log_path)
    combined = older + current
    return combined[-max_lines:]


def default_container_probe() -> bool | None:
    """Return True if a container named exactly ``kaine-cycle`` exists.

    Probe every available container runtime (docker, podman).  Return
    ``True`` as soon as any runtime lists ``kaine-cycle``.  Return ``None``
    if any present runtime raised, exited non-zero, or timed out.  Return
    ``False`` only when every present runtime answered cleanly with no match,
    or neither runtime exists.
    """
    any_failure = False
    for binary in ("docker", "podman"):
        if shutil.which(binary) is None:
            continue
        try:
            result = subprocess.run(
                [
                    binary,
                    "ps",
                    "-a",
                    "--filter",
                    "name=^kaine-cycle$",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except Exception:
            any_failure = True
            continue

        if result.returncode != 0:
            any_failure = True
            continue

        for line in result.stdout.splitlines():
            if line.strip() == "kaine-cycle":
                return True

    return None if any_failure else False


# Backward-compatible alias for callers that imported the old name.
default_docker_probe = default_container_probe
