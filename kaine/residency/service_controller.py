# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generalized service controllers for external model servers.

The residency manager uses these to stop, start and health-check the organ
(llama-server), the STT server (Speaches) and the TTS server (Chatterbox).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)

COMPOSE_FILE = Path("compose/kaine.yml")

DEFAULT_SPEACHES_URL = "http://127.0.0.1:8000"
DEFAULT_CHATTERBOX_URL = "http://127.0.0.1:8883"


@runtime_checkable
class ServiceController(Protocol):
    """Async start/stop/health for one external model server."""

    @property
    def name(self) -> str:
        pass  # protocol stub

    async def stop(self) -> bool:
        pass  # protocol stub

    async def start(self) -> bool:
        pass  # protocol stub

    async def health(self) -> tuple[bool, str]:
        pass  # protocol stub


_compose_cmd: list[str] | None = None


def _find_compose_cmd() -> list[str]:
    global _compose_cmd
    if _compose_cmd is not None:
        return _compose_cmd
    for binary in ("podman", "docker"):
        if shutil.which(binary):
            _compose_cmd = [binary, "compose"]
            return _compose_cmd
    raise RuntimeError("neither podman nor docker found on PATH")


class ComposeServiceController:
    """Manages a container service through compose stop/start."""

    def __init__(
        self,
        *,
        name: str,
        compose_file: Path | str = COMPOSE_FILE,
        health_url: str,
        health_path: str = "/",
        health_ok: Callable[[int], bool] = lambda status: status < 400,
        shared: bool = False,
        runner: Optional[Callable[..., Any]] = None,
        health_probe: Optional[Callable[[], Awaitable[tuple[bool, str]]]] = None,
    ) -> None:
        self._name = name
        self._compose_file = Path(compose_file)
        self._health_url = health_url.rstrip("/")
        self._health_path = health_path
        self._health_ok = health_ok
        self._shared = shared
        self._runner = runner
        self._health_probe = health_probe

    @property
    def name(self) -> str:
        return self._name

    def _run(self, cmd: list[str]) -> int:
        run = self._runner or subprocess.run
        result = run(cmd, capture_output=True, text=True, timeout=60.0, check=False)
        if result.returncode != 0:
            log.warning(
                "%s exited %d: %s",
                " ".join(cmd[:4]),
                result.returncode,
                (result.stderr or "").strip()[:200],
            )
        return result.returncode

    async def stop(self) -> bool:
        if self._shared:
            log.info("%s is shared; leaving it running", self._name)
            return False
        cmd = _find_compose_cmd() + ["-f", str(self._compose_file), "stop", self._name]
        rc = await asyncio.to_thread(self._run, cmd)
        return rc == 0

    async def start(self) -> bool:
        if self._shared:
            log.info("%s is shared; not starting", self._name)
            return False
        cmd = _find_compose_cmd() + [
            "-f", str(self._compose_file), "up", "-d", self._name,
        ]
        rc = await asyncio.to_thread(self._run, cmd)
        return rc == 0

    async def health(self) -> tuple[bool, str]:
        if self._health_probe is not None:
            return await self._health_probe()
        import httpx

        url = self._health_url + self._health_path
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                resp = await client.get(url)
            if self._health_ok(resp.status_code):
                return True, "%s ok (HTTP %d)" % (self._health_path, resp.status_code)
            return False, "%s returned HTTP %d" % (self._health_path, resp.status_code)
        except Exception as exc:
            return False, "health probe failed: %s" % exc


class NativeOrganController:
    """Manages the native-process organ (llama-server) via the lifecycle module."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        shared: bool = False,
        stop_fn: Optional[Callable[..., int]] = None,
        start_fn: Optional[Callable[..., int]] = None,
        probe_fn: Optional[Callable[..., tuple[bool, str]]] = None,
    ) -> None:
        self._config = config
        self._shared = shared
        self._stop_fn = stop_fn
        self._start_fn = start_fn
        self._probe_fn = probe_fn

    @property
    def name(self) -> str:
        return "model_server"

    async def stop(self) -> bool:
        if self._shared:
            log.info("model_server is shared; leaving it running")
            return False
        if self._stop_fn is not None:
            rc = await asyncio.to_thread(self._stop_fn, self._config)
        else:
            from kaine.organ_server.lifecycle import cmd_stop

            rc = await asyncio.to_thread(
                cmd_stop,
                self._config,
                out=lambda s: log.info("model-server stop: %s", s.rstrip()),
            )
        return rc == 0

    async def start(self) -> bool:
        if self._shared:
            log.info("model_server is shared; not starting")
            return False
        if self._start_fn is not None:
            rc = await asyncio.to_thread(self._start_fn, self._config)
        else:
            from kaine.organ_server.lifecycle import cmd_start

            rc = await asyncio.to_thread(
                cmd_start,
                self._config,
                out=lambda s: log.info("model-server start: %s", s.rstrip()),
            )
        return rc == 0

    async def health(self) -> tuple[bool, str]:
        if self._probe_fn is not None:
            return await asyncio.to_thread(self._probe_fn)

        from kaine.defaults import language_section_api_key, language_section_chat_url
        from kaine.organ_server.lifecycle import health_check
        from kaine.organ_server.served import ORGAN_GGUF_REPO

        language = self._config.get("language") or {}
        chat_url = language_section_chat_url(language)
        alias = str(language.get("model_id", ORGAN_GGUF_REPO))
        api_key = language_section_api_key(language)

        ok, detail = await asyncio.to_thread(
            health_check, chat_url, alias, api_key=api_key, timeout_s=5.0,
        )
        return ok, detail


def build_controllers(
    config: dict[str, Any],
) -> dict[str, ServiceController]:
    """Build controllers for all known services from the KAINE config."""
    from kaine.shared_services import is_shared

    vocal = config.get("vocal") or {}
    audition = config.get("audition") or {}

    chatterbox_url = str(
        vocal.get("chatterbox_url", DEFAULT_CHATTERBOX_URL)
    ).rstrip("/")
    speaches_url = str(
        audition.get("speaches_url", DEFAULT_SPEACHES_URL)
    ).rstrip("/")

    controllers: dict[str, ServiceController] = {}

    controllers["model_server"] = NativeOrganController(
        config=config,
        shared=is_shared(config, "model_server"),
    )
    controllers["kaine-speaches"] = ComposeServiceController(
        name="kaine-speaches",
        health_url=speaches_url,
        health_path="/v1/models",
        health_ok=lambda status: status == 200,
        shared=is_shared(config, "speaches"),
    )
    controllers["kaine-chatterbox"] = ComposeServiceController(
        name="kaine-chatterbox",
        health_url=chatterbox_url,
        health_path="/",
        health_ok=lambda status: status < 500,
        shared=is_shared(config, "chatterbox"),
    )
    return controllers
