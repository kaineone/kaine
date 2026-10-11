# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend-aware provisioning tests for sherpa-onnx speech models."""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest

from kaine.setup import provision
from kaine.setup.speech_models import DEFAULT_STT, MANIFEST, SpeechModel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_archive(
    path: Path,
    top_dir: str,
    files: dict[str, bytes | str],
) -> Path:
    files = dict(files)
    if "tokens.txt" in files:
        files["tokens.txt"] = "a 0\nb 1\n"
    with tarfile.open(path, "w:bz2") as tf:
        for relpath, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name=f"{top_dir}/{relpath}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def _patch_manifest(
    monkeypatch: pytest.MonkeyPatch,
    model_id: str,
    archive: Path,
    top_dir: str,
    required_files: tuple[str, ...],
    kind: str = "stt",
) -> None:
    monkeypatch.setitem(
        MANIFEST,
        model_id,
        SpeechModel(
            id=model_id,
            title="Test model",
            kind=kind,  # type: ignore[arg-type]
            url=str(archive),
            archive_name=archive.name,
            size_bytes=archive.stat().st_size,
            sha256=_sha256(archive),
            licence="MIT",
            top_dir=top_dir,
            required_files=required_files,
        ),
    )


def _empty_plan(*args: Any, **kwargs: Any) -> Any:
    return type("Plan", (), {"artifacts": []})()


def _patch_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(provision, "detect_organ_backend", lambda: "cpu")
    monkeypatch.setattr(provision, "plan_organ_download", _empty_plan)
    monkeypatch.setattr(provision, "run_organ_download", lambda *a, **k: [])
    monkeypatch.setattr(provision, "encoder_backend", lambda c: "dinov2")
    from kaine.setup import speech_models

    monkeypatch.setattr(speech_models, "models_dir", lambda: tmp_path)


def test_aux_models_omits_speaches_and_chatterbox_when_sherpa_selected() -> None:
    cfg = {
        "audition": {
            "backend": "sherpa_onnx",
            "stt_model_id": "Systran/faster-distil-whisper-medium.en",
        },
        "vox": {"backend": "sherpa_onnx"},
    }
    models = provision.aux_models(cfg)
    repos = {m.repo for m in models}
    assert "Systran/faster-distil-whisper-medium.en" not in repos
    assert "resemble-ai/chatterbox" not in repos
    assert any("emotion2vec" in m.purpose for m in models)
    assert any("memory embedder" in m.purpose for m in models)


def test_run_provision_consent_false_fetches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provision, "detect_organ_backend", lambda: "cpu")
    monkeypatch.setattr(provision, "plan_organ_download", _empty_plan)
    monkeypatch.setattr(provision, "run_organ_download", lambda *a, **k: [])
    cfg = {
        "modules": {},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
    }
    organ, aux = provision.run_provision(cfg, consent=False)
    assert organ == []
    assert aux == []


def test_run_provision_speech_consent_false_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "stt.tar.bz2"
    top_dir = "sherpa-onnx-test-stt"
    _make_archive(
        archive,
        top_dir,
        {
            "encoder_model.ort": b"enc",
            "decoder_model_merged.ort": b"dec",
            "tokens.txt": b"tok",
        },
    )
    _patch_manifest(
        monkeypatch,
        DEFAULT_STT,
        archive,
        top_dir,
        ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt"),
    )
    _patch_network(monkeypatch, tmp_path)

    cfg = {
        "modules": {},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
    }

    downloader_called = False

    def _downloader(_url: str, dest: str) -> None:
        nonlocal downloader_called
        downloader_called = True
        shutil.copyfile(str(archive), dest)

    from kaine.setup import speech_models

    organ, aux = provision.run_provision(
        cfg, consent=True, speech_consent=False, speech_downloader=_downloader
    )

    assert not downloader_called
    assert not speech_models.is_installed(DEFAULT_STT, tmp_path)
    not_fetched = [r for r in aux if r.repo == "sherpa-onnx speech models"]
    assert len(not_fetched) == 1
    assert not_fetched[0].ok is False
    assert not_fetched[0].purpose == "speech models (not fetched)"
    assert "explicit consent" in not_fetched[0].detail


def test_run_provision_with_speech_consent_true_fetches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "stt.tar.bz2"
    top_dir = "sherpa-onnx-test-stt"
    _make_archive(
        archive,
        top_dir,
        {
            "encoder_model.ort": b"enc",
            "decoder_model_merged.ort": b"dec",
            "tokens.txt": b"tok",
        },
    )
    _patch_manifest(
        monkeypatch,
        DEFAULT_STT,
        archive,
        top_dir,
        ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt"),
    )
    _patch_network(monkeypatch, tmp_path)

    cfg = {
        "modules": {},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
    }

    def _downloader(_url: str, dest: str) -> None:
        shutil.copyfile(str(archive), dest)

    from kaine.setup import speech_models

    organ, aux = provision.run_provision(
        cfg, consent=True, speech_consent=True, speech_downloader=_downloader
    )

    speech_results = [r for r in aux if r.repo == str(archive)]
    assert len(speech_results) == 1
    assert speech_results[0].ok is True
    assert (
        "installed" in speech_results[0].detail
        or "already installed" in speech_results[0].detail
    )
    assert speech_models.is_installed(DEFAULT_STT, tmp_path)


def test_main_speech_models_flag_enables_fetch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = {
        "modules": {},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
    }
    monkeypatch.setattr(provision, "_load_config", lambda: cfg)
    monkeypatch.setattr(provision, "detect_organ_backend", lambda: "cpu")
    monkeypatch.setattr(provision, "plan_organ_download", _empty_plan)
    monkeypatch.setattr(provision, "run_organ_download", lambda *a, **k: [])
    monkeypatch.setattr(provision, "encoder_backend", lambda c: "dinov2")
    monkeypatch.setattr(provision.shutil, "which", lambda _cmd: None)

    from kaine.setup import speech_models

    fetch_calls: list[str] = []

    def _fake_fetch(model_id: str, **kwargs: Any) -> speech_models.FetchResult:
        fetch_calls.append(model_id)
        return speech_models.FetchResult(
            model_id=model_id, ok=True, detail="installed (test)"
        )

    monkeypatch.setattr(speech_models, "fetch", _fake_fetch)

    provision.main(["--speech-models"])

    out = capsys.readouterr().out
    assert fetch_calls == [DEFAULT_STT]
    assert "Planned sherpa-onnx speech archives:" in out


def test_main_without_speech_models_flag_does_not_fetch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("KAINE_PROVISION_SPEECH_MODELS", raising=False)
    cfg = {
        "modules": {},
        "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
    }
    monkeypatch.setattr(provision, "_load_config", lambda: cfg)
    monkeypatch.setattr(provision, "detect_organ_backend", lambda: "cpu")
    monkeypatch.setattr(provision, "plan_organ_download", _empty_plan)
    monkeypatch.setattr(provision, "run_organ_download", lambda *a, **k: [])
    monkeypatch.setattr(provision, "encoder_backend", lambda c: "dinov2")
    monkeypatch.setattr(provision.shutil, "which", lambda _cmd: None)

    from kaine.setup import speech_models

    fetch_calls: list[str] = []

    def _fake_fetch(model_id: str, **kwargs: Any) -> speech_models.FetchResult:
        fetch_calls.append(model_id)
        return speech_models.FetchResult(
            model_id=model_id, ok=True, detail="installed (test)"
        )

    monkeypatch.setattr(speech_models, "fetch", _fake_fetch)

    return_code = provision.main([])

    out = capsys.readouterr().out
    assert fetch_calls == []
    assert "Planned sherpa-onnx speech archives:" in out
    assert any("speech models (not fetched)" in line for line in out.splitlines())
    assert return_code == 1
