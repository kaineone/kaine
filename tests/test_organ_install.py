# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the consented, hardware-aware organ downloader (kaine.setup.organ).

Real subprocess is mocked; HTTP is mocked. The downloader must run a REAL
`hf download` reporting real success/failure (never a faked no-op), pick the
right format(s) for the host's role, capture the resolved revision, and verify
the served alias against the configured [lingua].model_id.
"""
from __future__ import annotations

import json
import subprocess


from kaine.setup import organ
from kaine.setup.organ import (
    ORGAN_GGUF_REPO,
    ORGAN_SAFETENSORS_REPO,
    OrganDownloadResult,
    detect_organ_backend,
    plan_organ_download,
    run_organ_download,
    verify_served_alias,
)


# --- backend detection -------------------------------------------------------


def test_detect_backend_nvidia_studio():
    b = detect_organ_backend("cuda")
    assert b.available is True
    assert b.path == "studio"


def test_detect_backend_amd_core():
    b = detect_organ_backend("rocm")
    assert b.available is True
    assert b.path == "core"


def test_detect_backend_cpu_guide_only():
    b = detect_organ_backend("cpu")
    assert b.available is False
    assert b.path == ""


# --- plan: format selection --------------------------------------------------


def test_plan_nothing_when_lingua_disabled():
    plan = plan_organ_download({"lingua": False}, detect_organ_backend("cuda"))
    assert plan.needed is False
    assert plan.artifacts == ()


def test_plan_gguf_only_for_serve_only_host():
    plan = plan_organ_download(
        {"lingua": True}, detect_organ_backend("cuda"), config={"modules": {"lingua": True}}
    )
    assert plan.needed is True
    repos = [a.repo for a in plan.artifacts]
    assert repos == [ORGAN_GGUF_REPO]
    assert all(a.command[:2] == ["hf", "download"] for a in plan.artifacts)


def test_plan_adds_safetensors_when_stage2_enabled():
    config = {
        "modules": {"lingua": True, "hypnos": True},
        "hypnos": {"voice_alignment": {"enabled": True}},
    }
    plan = plan_organ_download(
        config["modules"], detect_organ_backend("cuda"), config=config
    )
    repos = sorted(a.repo for a in plan.artifacts)
    assert repos == sorted([ORGAN_GGUF_REPO, ORGAN_SAFETENSORS_REPO])
    assert plan.total_size_gb > 0


def test_plan_no_safetensors_when_stage2_disabled():
    config = {
        "modules": {"lingua": True, "hypnos": True},
        "hypnos": {"voice_alignment": {"enabled": False}},
    }
    plan = plan_organ_download(
        config["modules"], detect_organ_backend("cuda"), config=config
    )
    assert [a.repo for a in plan.artifacts] == [ORGAN_GGUF_REPO]


# --- run_organ_download: real subprocess, real success/failure ---------------


def test_no_download_without_consent(monkeypatch):
    calls = []
    monkeypatch.setattr(organ.shutil, "which", lambda _x: "/usr/bin/hf")
    plan = plan_organ_download({"lingua": True}, detect_organ_backend("cuda"))
    results = run_organ_download(
        plan, consent=False, runner=lambda *a, **k: calls.append(a)
    )
    assert results == []
    assert calls == []  # nothing ran


def test_real_download_reports_success_and_revision(monkeypatch):
    monkeypatch.setattr(organ.shutil, "which", lambda _x: "/usr/bin/hf")
    sha = "a" * 40
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        assert kwargs.get("check") is True  # real check=True
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"/home/u/.cache/huggingface/hub/.../snapshots/{sha}/model.gguf\n", stderr=""
        )

    plan = plan_organ_download({"lingua": True}, detect_organ_backend("cuda"))
    results = run_organ_download(plan, consent=True, runner=fake_run)
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].revision == sha
    assert captured["cmd"][:2] == ["hf", "download"]


def test_real_download_reports_failure(monkeypatch):
    monkeypatch.setattr(organ.shutil, "which", lambda _x: "/usr/bin/hf")

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="403 gated repo")

    plan = plan_organ_download({"lingua": True}, detect_organ_backend("cuda"))
    results = run_organ_download(plan, consent=True, runner=fake_run)
    assert results[0].ok is False
    assert "403" in results[0].detail


def test_download_honest_failure_when_hf_absent(monkeypatch):
    monkeypatch.setattr(organ.shutil, "which", lambda _x: None)
    ran = []
    plan = plan_organ_download({"lingua": True}, detect_organ_backend("cuda"))
    results = run_organ_download(
        plan, consent=True, runner=lambda *a, **k: ran.append(a)
    )
    assert results[0].ok is False
    assert "hf" in results[0].detail.lower()
    assert ran == []  # no faked success — nothing ran, honest failure


# --- verify_served_alias -----------------------------------------------------


class _Resp:
    def __init__(self, status, ids):
        self.status_code = status
        self._ids = ids

    def json(self):
        return {"data": [{"id": i} for i in self._ids]}


class _Client:
    def __init__(self, resp=None, raises=None):
        self._resp = resp
        self._raises = raises

    def get(self, url, *, headers=None, timeout=None):
        if self._raises:
            raise self._raises
        return self._resp


def test_verify_alias_match():
    client = _Client(_Resp(200, ["kaineone/Qwen3.5-4B-abliterated-GGUF"]))
    r = verify_served_alias(
        "http://127.0.0.1:11434/v1", "kaineone/Qwen3.5-4B-abliterated-GGUF", client=client
    )
    assert r.listed is True


def test_verify_alias_mismatch_actionable():
    client = _Client(_Resp(200, ["some-other-model"]))
    r = verify_served_alias(
        "http://127.0.0.1:11434/v1", "kaineone/Qwen3.5-4B-abliterated-GGUF", client=client
    )
    assert r.listed is False
    assert "some-other-model" in r.detail
    assert "--alias" in r.detail


def test_verify_alias_server_unreachable():
    client = _Client(raises=ConnectionError("refused"))
    r = verify_served_alias("http://127.0.0.1:11434/v1", "x", client=client)
    assert r.listed is False
    assert "unreachable" in r.detail


def test_verify_tolerates_root_without_v1():
    client = _Client(_Resp(200, ["x"]))
    r = verify_served_alias("http://127.0.0.1:11434", "x", client=client)
    assert r.listed is True


# --- revision state round-trip (provenance) ----------------------------------


def test_revision_state_round_trip(tmp_path):
    results = [
        OrganDownloadResult(
            repo=ORGAN_GGUF_REPO, fmt="gguf", ok=True, revision="b" * 40
        ),
        OrganDownloadResult(repo="other", fmt="gguf", ok=False, revision=None),
    ]
    path = tmp_path / "rev.json"
    written = organ.write_revision_state(results, path=str(path))
    assert written == str(path)
    data = json.loads(path.read_text())
    assert data == {ORGAN_GGUF_REPO: "b" * 40}
    assert organ.read_revision_state(str(path)) == {ORGAN_GGUF_REPO: "b" * 40}


def test_revision_state_absent_is_empty(tmp_path):
    assert organ.read_revision_state(str(tmp_path / "missing.json")) == {}


def test_revision_state_nothing_to_write(tmp_path):
    results = [OrganDownloadResult(repo="x", fmt="gguf", ok=True, revision=None)]
    assert organ.write_revision_state(results, path=str(tmp_path / "r.json")) is None


# --- provenance: revision flows into the run manifest's model_ids ------------


def test_gather_model_ids_pins_organ_revision(tmp_path, monkeypatch):
    """The published organ's resolved revision (captured by the downloader) is
    recorded as a covariate in the run manifest's model_ids — so a run pins the
    exact published snapshot."""
    from kaine.cycle.__main__ import _gather_model_ids

    sha = "c" * 40
    state = tmp_path / "organ_revisions.json"
    organ.write_revision_state(
        [
            OrganDownloadResult(
                repo=ORGAN_GGUF_REPO, fmt="gguf", ok=True, revision=sha
            )
        ],
        path=str(state),
    )
    monkeypatch.setattr(organ, "ORGAN_REVISION_STATE_PATH", str(state))

    ids = _gather_model_ids(
        {"lingua": {"model_id": ORGAN_GGUF_REPO}}, eval_chat_model_id=ORGAN_GGUF_REPO
    )
    assert ids["lingua"] == ORGAN_GGUF_REPO
    assert ids["lingua_revision"] == sha


def test_gather_model_ids_no_revision_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        organ, "ORGAN_REVISION_STATE_PATH", str(tmp_path / "absent.json")
    )
    from kaine.cycle.__main__ import _gather_model_ids

    ids = _gather_model_ids(
        {"lingua": {"model_id": ORGAN_GGUF_REPO}}, eval_chat_model_id=None
    )
    assert "lingua_revision" not in ids
