# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for external dependency detection + honest wizard provisioning."""
from __future__ import annotations

from kaine.setup import dependencies as deps
from kaine.setup.dependencies import (
    detect_dependencies,
    implied_external_deps,
)
from kaine.setup.__main__ import _provision_dependencies


class _Answers:
    def __init__(self, answers):
        self._answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self._answers.pop(0) if self._answers else ""


def _sink():
    buf: list[str] = []
    return buf, buf.append


# --- implied / detect --------------------------------------------------------


def test_implied_external_deps_maps_modules():
    # Redis is always implied; lingua→model_server, mnemos/empatheia→qdrant,
    # audition→speaches, vox→chatterbox.
    assert implied_external_deps({}) == ["redis"]
    assert set(implied_external_deps({"lingua": True})) == {"redis", "model_server"}
    assert set(implied_external_deps({"mnemos": True})) == {"redis", "qdrant"}
    assert set(implied_external_deps({"empatheia": True})) == {"redis", "qdrant"}
    assert set(implied_external_deps({"audition": True})) == {"redis", "speaches"}
    assert set(implied_external_deps({"vox": True})) == {"redis", "chatterbox"}


def test_detect_only_needed_deps(monkeypatch):
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    statuses = detect_dependencies({"lingua": True})
    names = {s.spec.name for s in statuses}
    assert names == {"redis", "model_server"}  # qdrant/speaches/chatterbox not needed
    assert all(s.running is False for s in statuses)


def test_detect_running_is_satisfied(monkeypatch):
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: True)
    statuses = detect_dependencies({"mnemos": True})
    assert all(s.satisfied for s in statuses)


def test_detect_redis_port_override(monkeypatch):
    seen_ports = []

    def _fake_port(port, **k):
        seen_ports.append(port)
        return False

    monkeypatch.setattr(deps, "_binary_present", lambda b: True)
    monkeypatch.setattr(deps, "_port_listening", _fake_port)
    detect_dependencies({}, redis_port=6479)
    assert 6479 in seen_ports


# --- provisioning (consent / guide / failure) --------------------------------


def test_provision_running_dep_is_not_offered(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: True)
    monkeypatch.setattr(deps, "_binary_present", lambda b: True)
    buf, out = _sink()
    ans = _Answers([])
    _provision_dependencies(
        {"modules": {"lingua": True}}, input_fn=ans, out=out, defaults=False
    )
    text = "".join(buf)
    assert "already running" in text
    assert ans.prompts == []  # nothing to consent to


def test_provision_command_runs_on_consent(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    ran = []
    monkeypatch.setattr(
        "kaine.setup.__main__.subprocess.run",
        lambda cmd, **k: ran.append((cmd, k)),
    )
    buf, out = _sink()
    # lingua → redis (command) + model_server (command). The model server is
    # launched by the dedicated organ step, so _provision_dependencies skips it
    # here (no prompt, no run) to avoid double-launching the same bootstrap;
    # only redis prompts and runs on consent.
    ans = _Answers(["y"])
    _provision_dependencies(
        {"modules": {"lingua": True}}, input_fn=ans, out=out, defaults=False
    )
    assert len(ran) == 1
    assert all(k.get("shell") is True for _c, k in ran)
    assert any("redis-bootstrap" in c for c, _k in ran)


def test_provision_command_skipped_without_consent(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    ran = []
    monkeypatch.setattr(
        "kaine.setup.__main__.subprocess.run", lambda cmd, **k: ran.append(cmd)
    )
    buf, out = _sink()
    ans = _Answers(["n"])
    _provision_dependencies(
        {"modules": {"lingua": True}}, input_fn=ans, out=out, defaults=False
    )
    assert ran == []
    assert "Run later" in "".join(buf)


def test_provision_guide_only_never_runs(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    ran = []
    monkeypatch.setattr(
        "kaine.setup.__main__.subprocess.run", lambda cmd, **k: ran.append(cmd)
    )
    buf, out = _sink()
    ans = _Answers([])  # vox → chatterbox is guide-only: no prompt
    _provision_dependencies(
        {"modules": {"vox": True}}, input_fn=ans, out=out, defaults=False
    )
    text = "".join(buf)
    assert ran == []  # guide services are never auto-run
    assert "chatterbox" in text
    assert "github.com/resemble-ai/chatterbox" in text
    # redis (command) WAS offered; chatterbox prompt never was.
    assert not any("chatterbox" in p for p in ans.prompts)


def test_provision_never_crashes_on_failure(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)

    def _boom(cmd, **k):
        raise RuntimeError("install blew up")

    monkeypatch.setattr("kaine.setup.__main__.subprocess.run", _boom)
    buf, out = _sink()
    ans = _Answers(["y", "y"])
    # Must not raise.
    _provision_dependencies(
        {"modules": {"lingua": True}}, input_fn=ans, out=out, defaults=False
    )
    assert "provisioning failed" in "".join(buf)


def test_provision_defaults_shows_but_does_not_run(monkeypatch):
    monkeypatch.setattr(deps, "_port_listening", lambda p, **k: False)
    monkeypatch.setattr(deps, "_binary_present", lambda b: False)
    ran = []
    monkeypatch.setattr(
        "kaine.setup.__main__.subprocess.run", lambda cmd, **k: ran.append(cmd)
    )
    buf, out = _sink()
    _provision_dependencies(
        {"modules": {"lingua": True}}, input_fn=lambda _p: "", out=out, defaults=True
    )
    assert ran == []
    assert "command:" in "".join(buf)
