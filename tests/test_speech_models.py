# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the consent-gated sherpa-onnx model fetcher.

All tests are fully offline: archives are built locally and the downloader is
injected, so no real network traffic occurs.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
from pathlib import Path
from typing import Any

import pytest

from kaine.setup.speech_models import (
    DEFAULT_STT,
    DEFAULT_TTS,
    MANIFEST,
    SpeechModel,
    describe,
    fetch,
    is_installed,
    main,
    model_dir,
    required_speech_models,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_archive(
    path: Path,
    top_dir: str,
    files: dict[str, bytes | str] | None = None,
    evil: Any = None,
) -> Path:
    files = dict(files or {})
    if "tokens.txt" in files:
        files["tokens.txt"] = "a 0\nb 1\n"
    with tarfile.open(path, "w:bz2") as tf:
        for relpath, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name=f"{top_dir}/{relpath}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        if evil is not None:
            evil(tf)
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


def _copy_downloader(archive: Path) -> Any:
    def _dl(_url: str, dest: str) -> None:
        shutil.copyfile(str(archive), dest)
    return _dl


def test_fetch_installs_model_and_writes_verified_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )
    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)
    marker_path = model_dir("test-model", tmp_path) / ".verified"
    assert marker_path.exists()
    assert "sha256" in marker_path.read_text()


def test_marker_less_install_is_not_installed_and_is_refetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )
    fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert is_installed("test-model", tmp_path)

    (model_dir("test-model", tmp_path) / ".verified").unlink()
    assert not is_installed("test-model", tmp_path)

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)


def test_tampered_install_is_not_installed_and_is_refetched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )
    fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert is_installed("test-model", tmp_path)

    target_file = model_dir("test-model", tmp_path) / "tokens.txt"
    with open(target_file, "ab") as f:
        f.write(b"extra")

    assert not is_installed("test-model", tmp_path)

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)
    assert target_file.read_text() == "a 0\nb 1\n"


def test_symlinked_target_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )

    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "tokens.txt").write_text("wrong")
    target = model_dir("test-model", tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(decoy, target_is_directory=True)

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)
    assert not target.is_symlink()
    assert (target / "tokens.txt").read_text() == "a 0\nb 1\n"


def test_dangling_symlink_target_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )

    target = model_dir("test-model", tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(tmp_path / "nowhere", target_is_directory=True)
    assert target.is_symlink()
    assert not target.exists()

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)
    assert not target.is_symlink()


def test_extract_without_data_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delattr(tarfile, "data_filter", raising=False)

    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
    _make_archive(
        archive,
        top_dir,
        {
            "encoder_model.ort": b"enc",
            "decoder_model_merged.ort": b"dec",
            "tokens.txt": b"tok",
            "subdir/nested.txt": b"nested",
        },
    )
    _patch_manifest(
        monkeypatch,
        "test-model",
        archive,
        top_dir,
        ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt", "subdir/nested.txt"),
    )

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert result.ok
    assert is_installed("test-model", tmp_path)
    assert (model_dir("test-model", tmp_path) / "subdir" / "nested.txt").exists()


def test_extract_rejects_absolute_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.bz2"
    top_dir = "sherpa-onnx-test"

    def _add_absolute(tf: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name="/etc/passwd")
        info.size = 3
        tf.addfile(info, io.BytesIO(b"pwd"))

    _make_archive(
        archive,
        top_dir,
        {"encoder_model.ort": b"enc", "decoder_model_merged.ort": b"dec", "tokens.txt": b"tok"},
        evil=_add_absolute,
    )
    _patch_manifest(
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )

    result = fetch("test-model", root=tmp_path, downloader=_copy_downloader(archive))
    assert not result.ok
    assert "absolute path" in result.detail


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, []),
        ({"audition": {"backend": "speaches"}}, []),
        (
            {"audition": {"backend": "sherpa_onnx", "transcription_enabled": True}},
            [DEFAULT_STT],
        ),
        (
            {"vox": {"backend": "sherpa_onnx"}},
            [DEFAULT_TTS],
        ),
        (
            {
                "audition": {"backend": "sherpa_onnx", "transcription_enabled": True},
                "vox": {"backend": "sherpa_onnx"},
            },
            [DEFAULT_STT, DEFAULT_TTS],
        ),
        (
            {"audition": {"backend": "sherpa_onnx", "transcription_enabled": False}},
            [],
        ),
        (
            {
                "audition": {"backend": " SHERPA_ONNX ", "transcription_enabled": True},
                "vox": {"backend": "Sherpa_ONNX"},
            },
            [DEFAULT_STT, DEFAULT_TTS],
        ),
    ],
)
def test_required_speech_models_backends(config: dict, expected: list[str]) -> None:
    assert required_speech_models(config) == expected


def test_required_speech_models_custom_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_stt = "moonshine-tiny-en"
    assert required_speech_models(
        {
            "audition": {
                "backend": "sherpa_onnx",
                "transcription_enabled": True,
                "sherpa_model_id": custom_stt,
            }
        }
    ) == [custom_stt]

    with pytest.warns(UserWarning, match="skipping unknown speech model id"):
        assert required_speech_models(
            {
                "audition": {
                    "backend": "sherpa_onnx",
                    "transcription_enabled": True,
                    "sherpa_model_id": "not-in-manifest",
                }
            }
        ) == []


def test_required_speech_models_unknown_tts_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.warns(UserWarning, match="skipping unknown speech model id"):
        assert required_speech_models(
            {"vox": {"backend": "sherpa_onnx", "sherpa_model_id": "not-in-manifest"}}
        ) == []


def test_describe_kokoro_names_both_licences() -> None:
    text = describe("kokoro-en")
    assert "Apache-2.0 (model)" in text
    assert "GPL-3.0-or-later" in text


def test_main_cli_fetch_with_injected_downloader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "test.tar.bz2"
    top_dir = "sherpa-onnx-test"
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
        monkeypatch, "test-model", archive, top_dir, ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
    )

    result = main(
        ["--stt", "test-model", "--yes", "--root", str(tmp_path)],
        input_fn=lambda prompt: "",
        downloader=_copy_downloader(archive),
    )
    assert result == 0
    assert is_installed("test-model", tmp_path)


def test_main_cli_unknown_model() -> None:
    result = main(["--stt", "not-a-model"], input_fn=lambda prompt: "")
    assert result == 2
