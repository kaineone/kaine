# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The organ-window controller really reuses the model-server lifecycle.

No pretend swap: unload calls model_server.cmd_stop, reload calls cmd_start, and
an accepted adapter is applied via the server's --lora launch flag.
"""
from __future__ import annotations

from pathlib import Path

from kaine.modules.hypnos.organ_window import OrganServerController
from kaine.setup.model_server import LORA_ADAPTER_ENV, build_launch_cmd


def test_build_launch_cmd_appends_lora_flag_when_adapter_given():
    cmd = build_launch_cmd(
        Path("/bin/llama-server"),
        gguf="/m/organ.gguf",
        alias="organ",
        chat_url="http://127.0.0.1:11434/v1",
        lora_adapter="/state/adapters/current",
    )
    assert "--lora" in cmd
    assert cmd[cmd.index("--lora") + 1] == "/state/adapters/current"


def test_build_launch_cmd_omits_lora_flag_without_adapter():
    cmd = build_launch_cmd(
        Path("/bin/llama-server"),
        gguf="/m/organ.gguf",
        alias="organ",
        chat_url="http://127.0.0.1:11434/v1",
    )
    assert "--lora" not in cmd


def test_controller_unload_calls_cmd_stop():
    stopped: list[dict] = []
    ctrl = OrganServerController(
        config={"k": "v"},
        stop_fn=lambda cfg: (stopped.append(cfg), 0)[1],
    )
    assert ctrl.unload() is True
    assert stopped == [{"k": "v"}]


def test_controller_reload_runs_preflight_then_start_then_probe():
    order: list[str] = []
    ctrl = OrganServerController(
        config={},
        start_fn=lambda cfg, *, adapter_path: (order.append(f"start:{adapter_path}"), 0)[1],
        preflight_fn=lambda cfg: (order.append("preflight"), True)[1],
        probe_fn=lambda: (order.append("probe"), True)[1],
    )
    assert ctrl.reload(adapter_path=Path("/a")) is True
    assert order == ["preflight", "start:/a", "probe"]


def test_controller_reload_reports_false_when_organ_does_not_answer():
    ctrl = OrganServerController(
        config={},
        start_fn=lambda cfg, *, adapter_path: 0,
        preflight_fn=lambda cfg: True,
        probe_fn=lambda: False,  # started but the alias never appeared
    )
    assert ctrl.reload(adapter_path=None) is False


def test_controller_reload_reports_false_when_start_fails():
    ctrl = OrganServerController(
        config={},
        start_fn=lambda cfg, *, adapter_path: 3,  # non-zero rc
        preflight_fn=lambda cfg: True,
        probe_fn=lambda: True,
    )
    assert ctrl.reload(adapter_path=None) is False


def test_controller_real_start_exports_lora_env(monkeypatch):
    """The default _start path exports LORA_ADAPTER_ENV around cmd_start so the
    launch-cmd builder attaches --lora, and restores the prior env after."""
    seen: list[str | None] = []

    def fake_cmd_start(config, *, out=None):
        seen.append(__import__("os").environ.get(LORA_ADAPTER_ENV))
        return 0

    monkeypatch.setattr("kaine.setup.model_server.cmd_start", fake_cmd_start)
    monkeypatch.delenv(LORA_ADAPTER_ENV, raising=False)

    ctrl = OrganServerController(config={}, preflight_fn=lambda cfg: True, probe_fn=lambda: True)
    ctrl.reload(adapter_path=Path("/state/adapters/current"))
    assert seen == ["/state/adapters/current"]
    # Env restored (no leak) after the start.
    import os

    assert LORA_ADAPTER_ENV not in os.environ
