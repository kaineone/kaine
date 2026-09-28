# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for speech_models verification helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.setup.speech_models import (
    MANIFEST,
    is_installed,
    model_dir,
    validate_tokens_file,
    verify_model_dir,
)


def _write_marker(path: Path, model_id: str, sha256: str, files: dict[str, int]) -> None:
    marker = {"model_id": model_id, "sha256": sha256, "files": files}
    (path / ".verified").write_text(json.dumps(marker), encoding="utf-8")


def test_validate_tokens_file_accepts_simple_format(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("a 0\nb 1\n", encoding="utf-8")
    validate_tokens_file(p)  # does not raise


def test_validate_tokens_file_accepts_whitespace_token(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("  2\n", encoding="utf-8")
    validate_tokens_file(p)  # does not raise


def test_validate_tokens_file_accepts_real_moonshine_and_kokoro_lines(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("PHVuaz4= 0\nPHM+ 1\n$ 0\n; 1\n", encoding="utf-8")
    validate_tokens_file(p)


def test_validate_tokens_file_accepts_real_empty_and_space_token_lines(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("31354: 31353\n17:  16\n", encoding="utf-8")
    validate_tokens_file(p)


def test_validate_tokens_file_rejects_random_bytes(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_bytes(b"\x80\x81\x82")
    with pytest.raises(ValueError, match="UTF-8"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_non_integer_id(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("a not_an_id\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integer"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_negative_id(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("a -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integer id"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no token"):
        validate_tokens_file(p)


def _moonshine_dir(tmp_path: Path, *, tokens: str = "a 0\nb 1\n") -> Path:
    d = tmp_path / "moonshine-base-en"
    d.mkdir()
    (d / "encoder_model.ort").write_bytes(b"enc")
    (d / "decoder_model_merged.ort").write_bytes(b"dec")
    (d / "tokens.txt").write_text(tokens, encoding="utf-8")
    return d


def test_verify_model_dir_rejects_missing_marker(tmp_path: Path) -> None:
    d = _moonshine_dir(tmp_path)
    with pytest.raises(ValueError, match="missing or invalid .verified marker"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_wrong_sha256(tmp_path: Path) -> None:
    d = _moonshine_dir(tmp_path)
    _write_marker(
        d,
        "moonshine-base-en",
        "0000000000000000000000000000000000000000000000000000000000000000",
        {},
    )
    with pytest.raises(ValueError, match="marker does not match"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_size_mismatch(tmp_path: Path) -> None:
    d = _moonshine_dir(tmp_path)
    model = MANIFEST["moonshine-base-en"]
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 9999,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 9,
        },
    )
    with pytest.raises(ValueError, match="file size mismatch"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_bad_tokens(tmp_path: Path) -> None:
    d = _moonshine_dir(tmp_path, tokens="bad no int\n")
    model = MANIFEST["moonshine-base-en"]
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 3,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 11,
        },
    )
    with pytest.raises(ValueError, match="tokens.txt"):
        verify_model_dir("moonshine-base-en", d)


def test_is_installed_false_for_bad_tokens(tmp_path: Path) -> None:
    root = tmp_path / "models"
    d = model_dir("moonshine-base-en", root)
    d.mkdir(parents=True)
    (d / "encoder_model.ort").write_bytes(b"enc")
    (d / "decoder_model_merged.ort").write_bytes(b"dec")
    (d / "tokens.txt").write_bytes(b"\xff")
    model = MANIFEST["moonshine-base-en"]
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 3,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 1,
        },
    )
    assert is_installed("moonshine-base-en", root) is False
