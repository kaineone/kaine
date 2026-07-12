# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the first-run wizard (kaine.setup)."""
from __future__ import annotations

import io
import subprocess
import sys
import tomllib
from pathlib import Path

from kaine.setup import tomlwriter
from kaine.setup.__main__ import main as setup_main
from kaine.setup.wizard import (
    ACK_PHRASE,
    implied_extras,
    propose_device_assignments,
    run_wizard,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int) -> dict:
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
        "backend": "cuda" if cuda else "cpu",
        "device": "cuda" if cuda else "cpu",
        "cuda_devices": cuda_devices,
        "gpu_count": cuda,
        "cpu_count": 16,
    }


class _Answers:
    """Scripted input_fn: pops answers in order; empty string if exhausted."""

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
# Pure helpers
# ----------------------------------------------------------------------------


def test_propose_devices_multi_gpu():
    d = propose_device_assignments(_host(cuda=2))
    assert d["hypnos.voice_alignment.training_device"] == "cuda:0"
    assert d["topos.device"] == "cuda:1"
    assert d["mnemos.device"] == "cpu"
    assert d["audition.emotion_device"] == "cpu"


def test_propose_devices_single_gpu():
    d = propose_device_assignments(_host(cuda=1))
    assert d["hypnos.voice_alignment.training_device"] == "cuda:0"
    assert d["topos.device"] == "cuda:0"
    assert d["mnemos.device"] == "cpu"


def test_propose_devices_cpu_only():
    d = propose_device_assignments(_host(cuda=0))
    assert all(v == "cpu" for v in d.values())


def test_implied_extras():
    shipped = _shipped()
    extras = implied_extras({"nous": True, "audition": False, "topos": False}, shipped)
    assert "reasoning" in extras
    # capture flags are off in shipped config, so no audio/vision
    assert "audio" not in extras
    assert "vision" not in extras


def test_implied_extras_playlist_feed_implies_audio_and_vision():
    # playlist mode decodes media for BOTH surfaces — cv2 video + av audio —
    # independently of the per-module capture flags (which the shipped file
    # leaves off). Closes the gap that would otherwise fail playlist audio on a
    # fresh research install.
    shipped = {"perception_feed": {"mode": "playlist"}}
    extras = implied_extras({}, shipped)
    assert "vision" in extras
    assert "audio" in extras


def test_implied_extras_live_feed_implies_audio_and_vision():
    shipped = {"perception_feed": {"mode": "live"}}
    extras = implied_extras({}, shipped)
    assert "vision" in extras
    assert "audio" in extras


def test_implied_extras_seeded_feed_implies_nothing_extra():
    # seeded is pure-numpy synthesis — no cv2/av decode dependency. Be precise:
    # do not over-install.
    shipped = {"perception_feed": {"mode": "seeded"}}
    extras = implied_extras({}, shipped)
    assert "vision" not in extras
    assert "audio" not in extras
    assert extras == []


def test_implied_extras_deduplicates():
    # topos capture + playlist feed both imply vision; the result must not repeat.
    shipped = {
        "topos": {"capture_enabled": True},
        "perception_feed": {"mode": "playlist"},
    }
    extras = implied_extras({"topos": True}, shipped)
    assert extras.count("vision") == 1
    assert extras.count("audio") == 1


# ----------------------------------------------------------------------------
# run_wizard behavior
# ----------------------------------------------------------------------------


def test_ack_required_aborts_without_writing():
    answers = _Answers(["no thanks"])  # wrong ack phrase
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=answers,
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
        probe_services=None,
    )
    assert result.acknowledged is False
    assert result.config == {}


def test_full_run_multi_gpu_produces_config():
    # Prompts after ack, in order:
    #  1 ack
    #  2 accept device assignments? -> y
    #  3..N enable <module>? for each MODULE_ORDER entry
    #  lingua model id
    #  research opt-in? -> n
    #  encryption? -> n
    from kaine.setup.wizard import MODULE_ORDER

    answers = [ACK_PHRASE, "y"]
    # enable only soma + lingua, the rest off
    for m in MODULE_ORDER:
        answers.append("y" if m in ("soma", "lingua") else "n")
    answers.append("my-model:latest")  # lingua model id
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=2),
        shipped_config=_shipped(),
        probe_services=lambda: {"served_models": ["my-model:latest"]},
    )
    assert result.acknowledged is True
    cfg = result.config
    assert cfg["modules"]["soma"] is True
    assert cfg["modules"]["lingua"] is True
    assert cfg["modules"]["echo"] is False
    assert cfg["lingua"]["model_id"] == "my-model:latest"
    assert cfg["hypnos"]["voice_alignment"]["training_device"] == "cuda:0"
    assert cfg["topos"]["device"] == "cuda:1"
    # research disabled
    assert "research_submission" not in cfg
    # the config round-trips through the emitter
    assert tomllib.loads(tomlwriter.dumps(cfg)) == cfg


def test_vox_enabled_requires_voice_id():
    from kaine.setup.wizard import MODULE_ORDER

    answers = [ACK_PHRASE, "y"]
    for m in MODULE_ORDER:
        answers.append("y" if m in ("lingua", "vox") else "n")
    answers.append("the-model")  # lingua model id
    # vox voice id: first blank (rejected), then a real one
    answers.append("")
    answers.append("Abigail.wav")
    answers.append("n")  # research
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
        probe_services=lambda: {},
    )
    assert result.config["modules"]["vox"] is True
    assert result.config["vox"]["predefined_voice_id"] == "Abigail.wav"


def test_metrics_only_when_opted_in():
    from kaine.setup.wizard import MODULE_ORDER

    answers = [ACK_PHRASE, "y"]
    for m in MODULE_ORDER:
        answers.append("n")
    # no lingua/vox/audition -> no model prompts
    answers.append("y")  # research opt-in
    answers.append("alice@example.com")  # recipient
    answers.append("n")  # encryption

    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        probe_services=lambda: {},
    )
    rs = result.config["research_submission"]
    assert rs["enabled"] is True
    assert rs["tier"] == "metrics"
    assert rs["recipient"] == "alice@example.com"
    assert result.config["transfer"]["recipient"] == "alice@example.com"


# ----------------------------------------------------------------------------
# --defaults / __main__
# ----------------------------------------------------------------------------


def test_defaults_writes_valid_file(tmp_path: Path):
    op = tmp_path / "kaine.operator.toml"
    out = io.StringIO()
    rc = setup_main(
        ["--defaults", "--operator-path", str(op)],
        input_fn=lambda _p: "",
        out=out,
    )
    assert rc == 0
    assert op.exists()
    with op.open("rb") as fh:
        data = tomllib.load(fh)
    assert "modules" in data
    # default safe set: soma on, echo off
    assert data["modules"]["soma"] is True
    assert data["modules"]["echo"] is False
    assert "security" not in data or not data["security"]["state_encryption"]["enabled"]
    # no metrics by default
    assert "research_submission" not in data


def test_defaults_does_not_modify_shipped_config():
    before = SHIPPED.read_bytes()
    out = io.StringIO()
    setup_main(
        ["--defaults", "--operator-path", "/tmp/kaine_wizard_test_op.toml"],
        input_fn=lambda _p: "",
        out=out,
    )
    assert SHIPPED.read_bytes() == before


def test_defaults_full_run_does_not_download_organ(tmp_path: Path, monkeypatch):
    """In --defaults mode the organ step shows the plan + command but downloads
    nothing (no consent path) — the wizard never installs silently."""
    # The "[--defaults] organ not downloaded" line is only reached when a
    # supported accelerator toolchain is present (backend.available); on a
    # CPU-only host the wizard prints the acquisition guide instead. Force an
    # available backend so this test deterministically exercises the --defaults
    # branch regardless of the CI host's accelerators (#68). Only `.available`
    # is overridden; the real backend's summary/plan compatibility is preserved.
    import dataclasses

    from kaine.setup import organ as organ_mod

    _real_detect = organ_mod.detect_organ_backend
    monkeypatch.setattr(
        organ_mod,
        "detect_organ_backend",
        lambda *a, **k: dataclasses.replace(_real_detect(*a, **k), available=True),
    )

    op = tmp_path / "op.toml"
    out = io.StringIO()
    rc = setup_main(
        ["--defaults", "--operator-path", str(op)],
        input_fn=lambda _p: "",
        out=out,
    )
    assert rc == 0
    text = out.getvalue()
    # lingua is on in the default set → organ step fires and shows the published
    # repo + command, but [--defaults] does not download.
    assert "Language organ download" in text
    assert "kaineone/Qwen3.5-4B-abliterated-GGUF" in text
    assert "[--defaults] organ not downloaded" in text


def test_provision_organ_declined_prints_guide():
    """Declining the organ download prints acquisition guidance and downloads
    nothing (mirrors _install_extras decline)."""
    from kaine.setup.__main__ import _provision_organ
    from kaine.setup import organ as organ_mod

    out: list[str] = []
    shipped = _shipped()
    # Operator answers "n" to the download prompt.
    _provision_organ(
        {"modules": {"lingua": True}},
        shipped=shipped,
        host={"backend": "cuda"},
        input_fn=lambda _p: "n",
        out=out.append,
        defaults=False,
    )
    text = "".join(out)
    assert "Skipped" in text
    assert f"huggingface.co/{organ_mod.ORGAN_GGUF_REPO}" in text


def test_provision_organ_skipped_when_lingua_disabled():
    from kaine.setup.__main__ import _provision_organ

    out: list[str] = []
    _provision_organ(
        {"modules": {"lingua": False}},
        shipped=_shipped(),
        host={"backend": "cuda"},
        input_fn=lambda _p: "y",
        out=out.append,
        defaults=False,
    )
    # No organ step at all.
    assert "Language organ download" not in "".join(out)


def test_provision_organ_consent_downloads_then_offers_launch(monkeypatch, tmp_path):
    """On consent the REAL downloader runs (mocked here), provenance is recorded,
    and the wizard offers the turnkey launch then verifies the served alias."""
    from kaine.setup.__main__ import _provision_organ
    from kaine.setup import organ as organ_mod

    sha = "d" * 40
    # Redirect the provenance state file out of the repo working tree.
    monkeypatch.setattr(
        organ_mod, "ORGAN_REVISION_STATE_PATH", str(tmp_path / "rev.json")
    )
    monkeypatch.setattr(organ_mod.shutil, "which", lambda _x: "/usr/bin/hf")

    def fake_run(cmd, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"/cache/snapshots/{sha}/m.gguf\n", stderr=""
        )

    monkeypatch.setattr(organ_mod.subprocess, "run", fake_run)
    # Stub the server launch subprocess in __main__ and the served-alias verify.
    import kaine.setup.__main__ as setup_main_mod

    monkeypatch.setattr(
        setup_main_mod.subprocess, "run", lambda *a, **k: None
    )
    from kaine.setup.organ import ServedAliasResult

    monkeypatch.setattr(
        organ_mod, "verify_served_alias",
        lambda *a, **k: ServedAliasResult(
            listed=True, served=("kaineone/Qwen3.5-4B-abliterated-GGUF",),
            detail="matches",
        ),
    )

    answers = iter(["y", "y"])  # download? yes; launch? yes
    out: list[str] = []
    _provision_organ(
        {"modules": {"lingua": True}},
        shipped=_shipped(),
        host={"backend": "cuda"},
        input_fn=lambda _p: next(answers, ""),
        out=out.append,
        defaults=False,
    )
    text = "".join(out)
    assert "[ok]" in text
    assert "served-name OK" in text


def test_defaults_subprocess_smoke(tmp_path: Path):
    op = tmp_path / "op.toml"
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.setup", "--defaults", "--operator-path", str(op)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    with op.open("rb") as fh:
        tomllib.load(fh)
