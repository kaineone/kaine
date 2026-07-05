# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.modules.praxis.whitelist import CommandWhitelist

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionRequest:
    pass


@dataclass(frozen=True)
class FileWriteRequest(ActionRequest):
    name: str           # relative path within the sandbox
    content: str        # text content (kept text-only for v1; binary is later)


@dataclass(frozen=True)
class NotifyRequest(ActionRequest):
    title: str
    body: str
    urgency: str = "normal"  # "low" | "normal" | "critical"


@dataclass(frozen=True)
class ShellRequest(ActionRequest):
    command: str
    args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionResult:
    success: bool
    elapsed_ms: float
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Effector(Protocol):
    @property
    def name(self) -> str: ...

    async def act(self, request: ActionRequest) -> ActionResult: ...


def _now_ms() -> float:
    return time.monotonic() * 1000.0


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        # Hardening the perms is best-effort: filesystems that don't support
        # POSIX modes (e.g. some network/Windows mounts) can't honour the
        # request. The sandbox stays usable; we only lose the perm tightening,
        # so swallow the failure rather than break the effector. Debug-logged
        # for diagnosis when someone turns verbosity up.
        log.debug("best-effort chmod of %s to %o failed", path, mode, exc_info=True)


def _resolve_sandbox_path(sandbox: Path, requested_name: str) -> Path:
    """Resolve requested_name inside sandbox, refusing escapes."""
    if not requested_name or os.path.isabs(requested_name):
        raise ValueError("sandbox violation: name must be relative")
    sandbox = sandbox.resolve()
    candidate = (sandbox / requested_name).resolve()
    try:
        candidate.relative_to(sandbox)
    except ValueError as exc:
        raise ValueError(f"sandbox violation: {requested_name!r}") from exc
    return candidate


class FileWriteEffector:
    name: str = "file_write"

    def __init__(self, sandbox_path: Path | str, max_bytes: int = 1_048_576) -> None:
        self._sandbox = Path(sandbox_path)
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = int(max_bytes)

    async def act(self, request: ActionRequest) -> ActionResult:
        start = _now_ms()
        try:
            if not isinstance(request, FileWriteRequest):
                raise TypeError("FileWriteEffector requires FileWriteRequest")
            payload_bytes = request.content.encode("utf-8")
            if len(payload_bytes) > self._max_bytes:
                raise ValueError(
                    f"content exceeds max_bytes ({len(payload_bytes)} > {self._max_bytes})"
                )
            # The sandbox holds entity-authored files; create it owner-only
            # (0700) regardless of the ambient umask, mirroring the snapshot
            # hardening so it is never group/world-readable.
            self._sandbox.mkdir(mode=0o700, parents=True, exist_ok=True)
            _chmod_quietly(self._sandbox, 0o700)
            target = _resolve_sandbox_path(self._sandbox, request.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(request.content, encoding="utf-8")
            return ActionResult(
                success=True,
                elapsed_ms=_now_ms() - start,
                metadata={"bytes": len(payload_bytes)},
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                elapsed_ms=_now_ms() - start,
                error=f"{type(exc).__name__}: {exc}",
            )


class NotifyEffector:
    name: str = "notify"

    def __init__(
        self,
        notification_command: str = "notify-send",
        fallback_log_path: Optional[Path | str] = None,
    ) -> None:
        self._notify_cmd = notification_command
        self._fallback_log_path = (
            Path(fallback_log_path) if fallback_log_path is not None else None
        )

    async def act(self, request: ActionRequest) -> ActionResult:
        start = _now_ms()
        try:
            if not isinstance(request, NotifyRequest):
                raise TypeError("NotifyEffector requires NotifyRequest")
            if shutil.which(self._notify_cmd):
                proc = await asyncio.create_subprocess_exec(
                    self._notify_cmd,
                    "-u",
                    request.urgency,
                    request.title,
                    request.body,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"{self._notify_cmd} exited {proc.returncode}: {stderr.decode().strip()}"
                    )
                return ActionResult(
                    success=True,
                    elapsed_ms=_now_ms() - start,
                    metadata={"transport": "notify-send"},
                )
            # Fallback: write a line to the log path.
            if self._fallback_log_path is not None:
                self._fallback_log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._fallback_log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"[{request.urgency}] {request.title} :: {request.body}\n")
                return ActionResult(
                    success=True,
                    elapsed_ms=_now_ms() - start,
                    metadata={"transport": "log-fallback"},
                )
            raise RuntimeError("no notification transport available")
        except Exception as exc:
            return ActionResult(
                success=False,
                elapsed_ms=_now_ms() - start,
                error=f"{type(exc).__name__}: {exc}",
            )


class ShellEffector:
    name: str = "shell"

    def __init__(self, whitelist: CommandWhitelist) -> None:
        self._whitelist = whitelist

    async def act(self, request: ActionRequest) -> ActionResult:
        start = _now_ms()
        try:
            if not isinstance(request, ShellRequest):
                raise TypeError("ShellEffector requires ShellRequest")
            entry = self._whitelist.match(request.command, list(request.args))
            if entry is None:
                raise ValueError(
                    f"command {request.command!r} not in whitelist or args disallowed"
                )
            proc = await asyncio.create_subprocess_exec(
                entry.command,
                *request.args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=entry.cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=entry.timeout_s
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"command {request.command!r} timed out")
            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(
                    f"{request.command!r} exited {proc.returncode}: {err_text[:200]}"
                )
            return ActionResult(
                success=True,
                elapsed_ms=_now_ms() - start,
                metadata={"returncode": proc.returncode, "stdout_bytes": len(stdout)},
            )
        except Exception as exc:
            return ActionResult(
                success=False,
                elapsed_ms=_now_ms() - start,
                error=f"{type(exc).__name__}: {exc}",
            )
