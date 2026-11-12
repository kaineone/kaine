# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import subprocess
from typing import Any

import pytest

from kaine.residency import service_controller as sc
from kaine.residency.service_controller import (
    ComposeServiceController,
    NativeOrganController,
    ServiceController,
    build_controllers,
)


def _runner(rc: int = 0) -> Any:
    recorded: list[list[str]] = []

    def run(cmd: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded.append(list(cmd))
        return subprocess.CompletedProcess(args=list(cmd), returncode=rc, stdout="", stderr="")

    run.recorded = recorded  # type: ignore[attr-defined]
    return run


@pytest.fixture(autouse=True)
def _reset_compose_cache() -> None:
    sc._compose_cmd = None
    yield  # type: ignore[misc]
    sc._compose_cmd = None


def _ctrl(
    *,
    shared: bool = False,
    runner: Any = None,
    health_probe: Any = None,
    health_ok: Any = None,
) -> ComposeServiceController:
    return ComposeServiceController(
        name="test-svc",
        compose_file="compose/test.yml",
        health_url="http://127.0.0.1:9999",
        health_path="/health",
        health_ok=health_ok or (lambda s: s == 200),
        shared=shared,
        runner=runner or _runner(0),
        health_probe=health_probe,
    )


# -- ComposeServiceController ------------------------------------------------


@pytest.mark.asyncio
async def test_compose_stop_runs_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    runner = _runner(0)
    ctrl = _ctrl(runner=runner)
    assert await ctrl.stop() is True
    assert len(runner.recorded) == 1
    cmd = runner.recorded[0]
    assert cmd[-2:] == ["stop", "test-svc"]
    assert "-f" in cmd
    assert "compose/test.yml" in cmd


@pytest.mark.asyncio
async def test_compose_stop_shared_refuses() -> None:
    runner = _runner(0)
    ctrl = _ctrl(shared=True, runner=runner)
    assert await ctrl.stop() is False
    assert runner.recorded == []


@pytest.mark.asyncio
async def test_compose_start_runs_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    runner = _runner(0)
    ctrl = _ctrl(runner=runner)
    assert await ctrl.start() is True
    cmd = runner.recorded[0]
    assert "up" in cmd
    assert "-d" in cmd
    assert cmd[-1] == "test-svc"


@pytest.mark.asyncio
async def test_compose_start_shared_refuses() -> None:
    runner = _runner(0)
    ctrl = _ctrl(shared=True, runner=runner)
    assert await ctrl.start() is False
    assert runner.recorded == []


@pytest.mark.asyncio
async def test_compose_stop_returns_false_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    runner = _runner(1)
    ctrl = _ctrl(runner=runner)
    assert await ctrl.stop() is False


@pytest.mark.asyncio
async def test_compose_health_uses_injected_probe() -> None:
    async def probe() -> tuple[bool, str]:
        return True, "ok"

    ctrl = _ctrl(health_probe=probe)
    assert await ctrl.health() == (True, "ok")


@pytest.mark.asyncio
async def test_compose_health_probe_failure() -> None:
    async def probe() -> tuple[bool, str]:
        return False, "connection refused"

    ctrl = _ctrl(health_probe=probe)
    ok, detail = await ctrl.health()
    assert ok is False
    assert "connection refused" in detail


@pytest.mark.asyncio
async def test_compose_health_httpx_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    import httpx as real_httpx

    monkeypatch.setattr(real_httpx, "AsyncClient", lambda **kw: FakeClient())
    ctrl = _ctrl()
    ok, detail = await ctrl.health()
    assert ok is True
    assert "200" in detail


@pytest.mark.asyncio
async def test_compose_health_httpx_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 503

    class FakeClient:
        async def get(self, url: str) -> FakeResponse:
            return FakeResponse()

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

    import httpx as real_httpx

    monkeypatch.setattr(real_httpx, "AsyncClient", lambda **kw: FakeClient())
    ctrl = _ctrl()
    ok, detail = await ctrl.health()
    assert ok is False
    assert "503" in detail


# -- NativeOrganController ---------------------------------------------------


@pytest.mark.asyncio
async def test_native_stop_calls_injected_fn() -> None:
    ctrl = NativeOrganController(config={}, stop_fn=lambda c: 0)
    assert await ctrl.stop() is True


@pytest.mark.asyncio
async def test_native_stop_nonzero_returns_false() -> None:
    ctrl = NativeOrganController(config={}, stop_fn=lambda c: 1)
    assert await ctrl.stop() is False


@pytest.mark.asyncio
async def test_native_stop_shared_refuses() -> None:
    calls: list[int] = []
    ctrl = NativeOrganController(
        config={},
        shared=True,
        stop_fn=lambda c: (calls.append(1), 0)[1],  # type: ignore[return-value]
    )
    assert await ctrl.stop() is False
    assert calls == []


@pytest.mark.asyncio
async def test_native_start_calls_injected_fn() -> None:
    ctrl = NativeOrganController(config={}, start_fn=lambda c: 0)
    assert await ctrl.start() is True


@pytest.mark.asyncio
async def test_native_start_nonzero_returns_false() -> None:
    ctrl = NativeOrganController(config={}, start_fn=lambda c: 3)
    assert await ctrl.start() is False


@pytest.mark.asyncio
async def test_native_health_injected_probe() -> None:
    ctrl = NativeOrganController(
        config={},
        probe_fn=lambda: (True, "serving organ"),
    )
    assert await ctrl.health() == (True, "serving organ")


@pytest.mark.asyncio
async def test_native_health_unhealthy() -> None:
    ctrl = NativeOrganController(
        config={},
        probe_fn=lambda: (False, "timeout"),
    )
    ok, detail = await ctrl.health()
    assert ok is False
    assert "timeout" in detail


@pytest.mark.asyncio
async def test_native_name_is_model_server() -> None:
    ctrl = NativeOrganController(config={})
    assert ctrl.name == "model_server"


# -- build_controllers -------------------------------------------------------


def test_build_controllers_returns_three() -> None:
    controllers = build_controllers({})
    assert set(controllers.keys()) == {"model_server", "kaine-speaches", "kaine-chatterbox"}


def test_build_controllers_shared_propagates() -> None:
    config: dict[str, Any] = {"services": {"model_server": {"shared": True}}}
    controllers = build_controllers(config)
    organ = controllers["model_server"]
    assert isinstance(organ, NativeOrganController)
    assert organ._shared is True


def test_build_controllers_uses_config_urls() -> None:
    config: dict[str, Any] = {
        "vocal": {"chatterbox_url": "http://10.0.0.1:9000"},
        "audition": {"speaches_url": "http://10.0.0.2:8001"},
    }
    controllers = build_controllers(config)
    cb = controllers["kaine-chatterbox"]
    sp = controllers["kaine-speaches"]
    assert isinstance(cb, ComposeServiceController)
    assert isinstance(sp, ComposeServiceController)
    assert cb._health_url == "http://10.0.0.1:9000"
    assert sp._health_url == "http://10.0.0.2:8001"


# -- _find_compose_cmd -------------------------------------------------------


def test_find_compose_cmd_podman(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/podman" if name == "podman" else None)
    assert sc._find_compose_cmd() == ["podman", "compose"]


def test_find_compose_cmd_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    assert sc._find_compose_cmd() == ["docker", "compose"]


def test_find_compose_cmd_neither(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="neither"):
        sc._find_compose_cmd()


# -- protocol conformance ----------------------------------------------------


def test_compose_satisfies_protocol() -> None:
    ctrl = _ctrl()
    assert isinstance(ctrl, ServiceController)


def test_native_satisfies_protocol() -> None:
    ctrl = NativeOrganController(config={})
    assert isinstance(ctrl, ServiceController)
