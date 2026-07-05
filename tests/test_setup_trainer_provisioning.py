# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for hardware-aware voice-alignment trainer provisioning (kaine.setup).

Hermetic: no real unsloth, no real entity, no real training subprocess. The
probe's subprocess.run is monkeypatched and interpreter paths are temp files, so
nothing heavy or external is ever invoked.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from kaine.setup import tomlwriter, trainer_provisioning
from kaine.setup.wizard import ACK_PHRASE, MODULE_ORDER, run_wizard

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, backend: str, cuda: int = 0) -> dict:
    """Host dict variant that sets an explicit GPU backend."""
    cuda_devices = [
        {
            "index": i,
            "device": f"cuda:{i}",
            "name": f"GPU{i}",
            "total_vram_gb": 24.0,
            "free_vram_gb": 20.0,
        }
        for i in range(cuda)
    ]
    return {
        "backend": backend,
        "device": backend,
        "cuda_devices": cuda_devices,
        "gpu_count": cuda,
        "cpu_count": 16,
    }


class _Answers:
    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._answers:
            return self._answers.pop(0)
        return ""


def _collect_out() -> tuple[list[str], callable]:
    buf: list[str] = []
    return buf, buf.append


# ----------------------------------------------------------------------------
# trainer_guidance: vendor -> guidance mapping
# ----------------------------------------------------------------------------


def test_guidance_cuda_is_unsloth_studio():
    g = trainer_provisioning.trainer_guidance("cuda")
    assert g.available is True
    assert "Studio" in g.name
    assert g.guide_url
    assert g.guide_steps


def test_guidance_cuda_mentions_transformers_v5():
    # The CUDA guidance must tell operators about the transformers v5 requirement
    # and provide the upgrade command so they don't hit "model type qwen3_5 not
    # recognized" during a Qwen3.5 training run.
    g = trainer_provisioning.trainer_guidance("cuda")
    steps_text = " ".join(g.guide_steps)
    assert "transformers" in steps_text.lower()
    assert "unsloth_zoo" in steps_text
    assert "force-reinstall" in steps_text


def test_guidance_rocm_is_unsloth_core_not_studio():
    g = trainer_provisioning.trainer_guidance("rocm")
    assert g.available is True
    assert "core" in g.name
    assert "Studio" not in g.name
    assert g.guide_url
    assert g.guide_steps


def test_guidance_cpu_mps_xpu_unavailable():
    for backend in ("cpu", "mps", "xpu", "something-unknown"):
        g = trainer_provisioning.trainer_guidance(backend)
        assert g.available is False
        assert "unavailable" in g.summary.lower()
        # The unavailable path is informational, never an install pointer.
        assert g.guide_url == ""


# ----------------------------------------------------------------------------
# probe_trainer: real probe, found vs not-found, never fakes, never raises
# ----------------------------------------------------------------------------


def test_probe_not_found_when_interpreter_missing():
    found, detail = trainer_provisioning.probe_trainer(
        "/nonexistent/python", backend="cuda"
    )
    assert found is False
    assert "not found" in detail


def test_probe_no_candidate_for_rocm_without_path():
    # ROCm/unsloth-core has no fixed location; with no configured path there is
    # no candidate to probe (and we must NOT fall back to the Studio default).
    found, detail = trainer_provisioning.probe_trainer(None, backend="rocm")
    assert found is False
    assert "no candidate" in detail


def test_probe_found_when_import_succeeds(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")  # exists; never actually run (mocked)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    captured = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        assert kwargs.get("shell") is not True  # explicit argv, no shell
        return _Proc()

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", _fake_run)
    found, detail = trainer_provisioning.probe_trainer(fake_py, backend="cuda")
    assert found is True
    assert str(fake_py) in detail
    # Probed the real interpreter with an explicit `import unsloth` argv.
    assert captured["argv"][0] == str(fake_py)
    assert captured["argv"][-1] == "import unsloth"


def test_probe_not_found_when_import_fails(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'unsloth'"

    monkeypatch.setattr(
        trainer_provisioning.subprocess, "run", lambda *a, **k: _Proc()
    )
    found, detail = trainer_provisioning.probe_trainer(fake_py, backend="cuda")
    assert found is False
    assert "cannot import unsloth" in detail


def test_probe_never_raises_on_os_error(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    def _boom(*a, **k):
        raise OSError("exec format error")

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", _boom)
    found, detail = trainer_provisioning.probe_trainer(fake_py, backend="cuda")
    assert found is False
    assert "could not launch" in detail


def test_probe_never_raises_on_timeout(tmp_path, monkeypatch):
    import subprocess as _sp

    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    def _timeout(*a, **k):
        raise _sp.TimeoutExpired(cmd="python", timeout=1.0)

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", _timeout)
    found, detail = trainer_provisioning.probe_trainer(fake_py, backend="cuda")
    assert found is False
    assert "timed out" in detail


def test_studio_default_interpreter_is_home_relative():
    # No personal absolute path: the default candidate is under ~/.unsloth.
    p = trainer_provisioning.STUDIO_DEFAULT_INTERPRETER
    assert p.is_relative_to(Path.home())
    assert ".unsloth" in p.parts


# ----------------------------------------------------------------------------
# probe_transformers_version: version check in external trainer env
# ----------------------------------------------------------------------------


def test_transformers_version_ok_when_v5(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    class _Proc:
        returncode = 0
        stdout = "5.0.0"
        stderr = ""

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", lambda *a, **k: _Proc())
    ok, detail = trainer_provisioning.probe_transformers_version(fake_py, backend="cuda")
    assert ok is True
    assert "5.0.0" in detail


def test_transformers_version_fails_when_v4(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    class _Proc:
        returncode = 0
        stdout = "4.57.6"
        stderr = ""

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", lambda *a, **k: _Proc())
    ok, detail = trainer_provisioning.probe_transformers_version(fake_py, backend="cuda")
    assert ok is False
    assert "4.57.6" in detail
    # Must include the upgrade command so operators know exactly what to run.
    assert "unsloth_zoo" in detail
    assert "force-reinstall" in detail


def test_transformers_version_fails_when_absent(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    class _Proc:
        returncode = 0
        stdout = "absent"
        stderr = ""

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", lambda *a, **k: _Proc())
    ok, detail = trainer_provisioning.probe_transformers_version(fake_py, backend="cuda")
    assert ok is False
    assert "not installed" in detail


def test_transformers_version_missing_interpreter():
    ok, detail = trainer_provisioning.probe_transformers_version(
        "/nonexistent/python", backend="cuda"
    )
    assert ok is False
    assert "not found" in detail


def test_transformers_version_no_candidate_rocm():
    ok, detail = trainer_provisioning.probe_transformers_version(None, backend="rocm")
    assert ok is False
    assert "no candidate" in detail


def test_transformers_version_never_raises_on_os_error(tmp_path, monkeypatch):
    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    def _boom(*a, **k):
        raise OSError("exec format error")

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", _boom)
    ok, detail = trainer_provisioning.probe_transformers_version(fake_py, backend="cuda")
    assert ok is False
    assert "could not launch" in detail


def test_transformers_version_never_raises_on_timeout(tmp_path, monkeypatch):
    import subprocess as _sp

    fake_py = tmp_path / "python"
    fake_py.write_text("#!/bin/sh\n")

    def _timeout(*a, **k):
        raise _sp.TimeoutExpired(cmd="python", timeout=1.0)

    monkeypatch.setattr(trainer_provisioning.subprocess, "run", _timeout)
    ok, detail = trainer_provisioning.probe_transformers_version(fake_py, backend="cuda")
    assert ok is False
    assert "timed out" in detail


def test_transformers_min_major_is_5():
    # Sentinel: if this changes, update all guidance text and the probe logic.
    assert trainer_provisioning.TRANSFORMERS_MIN_MAJOR == 5


# ----------------------------------------------------------------------------
# Wizard integration: the Stage-2 trainer step
# ----------------------------------------------------------------------------


def _base_answers(*, want_trainer: str) -> list[str]:
    """Answers up to and including the trainer-step yes/no.

    Enables only soma (no lingua/vox/audition prompts), accepts devices.
    """
    answers = [ACK_PHRASE, "y"]  # ack, accept device assignments
    for m in MODULE_ORDER:
        answers.append("y" if m == "soma" else "n")
    answers.append(want_trainer)  # "set up trainer now?"
    return answers


def test_wizard_records_trainer_python_on_consent():
    answers = _base_answers(want_trainer="y")
    answers.append("y")  # record this interpreter? -> yes
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()

    def _probe(interpreter, *, backend="cuda"):
        return (True, "/home/op/.unsloth/studio/unsloth_studio/bin/python: usable")

    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(backend="cuda", cuda=1),
        shipped_config=_shipped(),
        probe_services=lambda: {},
        probe_trainer=_probe,
    )
    va = result.config["hypnos"]["voice_alignment"]
    assert va["trainer_python"] == "/home/op/.unsloth/studio/unsloth_studio/bin/python"
    assert va["trainer_backend"] == "subprocess"
    # round-trips through the operator-config emitter
    assert tomllib.loads(tomlwriter.dumps(result.config)) == result.config


def test_wizard_does_not_record_when_probe_not_found():
    answers = _base_answers(want_trainer="y")
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()

    def _probe(interpreter, *, backend="cuda"):
        return (False, "/nonexistent: interpreter not found")

    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(backend="cuda", cuda=1),
        shipped_config=_shipped(),
        probe_services=lambda: {},
        probe_trainer=_probe,
    )
    # No trainer_python recorded — never a path that would fail at first sleep.
    assert "trainer_python" not in (
        (result.config.get("hypnos") or {}).get("voice_alignment") or {}
    )
    assert any("install per the steps" in line for line in out)


def test_wizard_unsupported_backend_reports_unavailable_no_error():
    answers = _base_answers(want_trainer="y")
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()

    calls = {"n": 0}

    def _probe(interpreter, *, backend="cuda"):  # should not be reached
        calls["n"] += 1
        return (True, "should-not-happen")

    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(backend="cpu", cuda=0),
        shipped_config=_shipped(),
        probe_services=lambda: {},
        probe_trainer=_probe,
    )
    assert result.acknowledged is True
    assert "trainer_python" not in (
        (result.config.get("hypnos") or {}).get("voice_alignment") or {}
    )
    assert any("unavailable" in line.lower() for line in out)
    # unavailable backend short-circuits before probing
    assert calls["n"] == 0


def test_wizard_skipped_when_operator_declines():
    answers = _base_answers(want_trainer="n")
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()

    def _probe(interpreter, *, backend="cuda"):
        raise AssertionError("probe must not run when trainer step is declined")

    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(backend="cuda", cuda=1),
        shipped_config=_shipped(),
        probe_services=lambda: {},
        probe_trainer=_probe,
    )
    # The device step still sets training_device, but no trainer_python is set.
    assert "trainer_python" not in (
        (result.config.get("hypnos") or {}).get("voice_alignment") or {}
    )
    assert any("skipped" in line.lower() for line in out)


def test_wizard_never_crashes_on_probe_exception():
    answers = _base_answers(want_trainer="y")
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()

    def _probe(interpreter, *, backend="cuda"):
        raise RuntimeError("probe blew up")

    # Must not propagate; the wizard completes acknowledged with no trainer set.
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(backend="cuda", cuda=1),
        shipped_config=_shipped(),
        probe_services=lambda: {},
        probe_trainer=_probe,
    )
    assert result.acknowledged is True
    assert "trainer_python" not in (
        (result.config.get("hypnos") or {}).get("voice_alignment") or {}
    )
    assert any("error" in line.lower() for line in out)
