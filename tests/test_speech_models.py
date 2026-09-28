# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the consent-gated sherpa-onnx model fetcher.

All tests are fully offline: archives are built locally and the downloader is
injected, so no real network traffic occurs.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from kaine.setup.speech_models import (
    MANIFEST,
    SpeechModel,
    _default_downloader,
    fetch,
    is_installed,
    main,
    model_dir,
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
    files = files or {}
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


@pytest.fixture
def local_downloader():
    def _downloader(url: str, dest_path: str) -> None:
        shutil.copy(url, dest_path)

    return _downloader


def test_fetch_installs_and_is_idempotent(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert res.ok
    assert res.detail == "installed"
    assert res.path == model_dir("test-stt", tmp_path)
    assert is_installed("test-stt", root=tmp_path)

    calls = []

    def counting_downloader(url: str, dest_path: str) -> None:
        calls.append((url, dest_path))

    res2 = fetch("test-stt", root=tmp_path, downloader=counting_downloader)
    assert res2.ok
    assert res2.detail == "already installed"
    assert not calls


def test_fetch_sha256_mismatch(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )
    monkeypatch.setitem(
        MANIFEST,
        "test-stt",
        dataclasses.replace(MANIFEST["test-stt"], sha256="0" * 64),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "sha256 mismatch" in res.detail
    assert not is_installed("test-stt", root=tmp_path)


def test_fetch_size_mismatch(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )
    monkeypatch.setitem(
        MANIFEST,
        "test-stt",
        dataclasses.replace(MANIFEST["test-stt"], size_bytes=archive.stat().st_size + 1),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "size mismatch" in res.detail
    assert not is_installed("test-stt", root=tmp_path)


def test_rejects_symlink_member(tmp_path, monkeypatch, local_downloader):
    def _evil(tf: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name="model/evil_link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
        evil=_evil,
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "extraction failed" in res.detail
    assert not is_installed("test-stt", root=tmp_path)


def test_rejects_path_traversal_member(tmp_path, monkeypatch, local_downloader):
    def _evil(tf: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name="model/../../evil.txt")
        data = b"evil"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
        evil=_evil,
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "extraction failed" in res.detail


def test_rejects_absolute_path_member(tmp_path, monkeypatch, local_downloader):
    def _evil(tf: tarfile.TarFile) -> None:
        info = tarfile.TarInfo(name="/absolute/evil.txt")
        data = b"evil"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
        evil=_evil,
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "extraction failed" in res.detail


def test_rejects_wrong_top_level_dir(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="wrong",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "extraction failed" in res.detail


def test_rejects_missing_required_file(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=tmp_path, downloader=local_downloader)
    assert not res.ok
    assert "required file missing" in res.detail


def test_cli_declines_consent_without_downloading(tmp_path, monkeypatch):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    calls = []

    def nope(*_args, **_kwargs) -> None:
        calls.append(True)

    rc = main(
        ["--root", str(tmp_path), "--stt", "test-stt"],
        input_fn=lambda _prompt: "n",
        downloader=nope,
    )
    assert rc == 0
    assert not calls


def test_cli_with_yes_fetches(tmp_path, monkeypatch, local_downloader):
    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    rc = main(
        ["--root", str(tmp_path), "--stt", "test-stt", "--yes"],
        downloader=local_downloader,
    )
    assert rc == 0
    assert is_installed("test-stt", root=tmp_path)


def test_cli_unknown_id_returns_2():
    assert main(["--stt", "not-a-real-model"]) == 2


def test_cli_stt_flag_rejects_tts_id():
    assert main(["--stt", "kokoro-en"]) == 2


def test_fetch_through_symlinked_root(tmp_path, monkeypatch, local_downloader):
    real = tmp_path / "real"
    link = tmp_path / "link"
    real.mkdir()
    try:
        os.symlink(real, link)
    except OSError:
        pytest.skip("symlinks not supported on this platform")

    archive = _make_archive(
        tmp_path / "model.tar.bz2",
        top_dir="model",
        files={"encoder_model.ort": b"e", "tokens.txt": b"t"},
    )
    _patch_manifest(
        monkeypatch,
        "test-stt",
        archive,
        top_dir="model",
        required_files=("encoder_model.ort", "tokens.txt"),
    )

    res = fetch("test-stt", root=link, downloader=local_downloader)
    assert res.ok
    assert res.detail == "installed"
    assert res.path == model_dir("test-stt", link)
    assert is_installed("test-stt", root=link)
    assert is_installed("test-stt", root=real)


def test_default_downloader_stops_at_max_bytes(tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self) -> None:
            self._remaining = 10

        def read(self, _n: int = -1) -> bytes:
            if self._remaining <= 0:
                return b""
            self._remaining -= 1
            return b"x" * 1024

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _url, timeout=60: FakeResponse(),
    )

    dest = tmp_path / "download.bin"
    with pytest.raises(ValueError, match="download exceeded the pinned size"):
        _default_downloader("http://example.com/model", str(dest), max_bytes=2048)


def test_manifest_is_pinned():
    assert set(MANIFEST.keys()) == {
        "moonshine-base-en",
        "moonshine-tiny-en",
        "kokoro-en",
    }
    assert (
        MANIFEST["moonshine-base-en"].sha256
        == "43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891"
    )
    assert (
        MANIFEST["moonshine-tiny-en"].sha256
        == "9ec31b342d8fa3240c3b81b8f82e1cf7e3ac467c93ca5a999b741d5887164f8d"
    )
    assert (
        MANIFEST["kokoro-en"].sha256
        == "c9f0dd393615805b0bab050c340834d5e684e732aec91c0e860cd30e982c08bd"
    )
