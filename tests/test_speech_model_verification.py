# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the speech-model verification helpers (kaine.speech_manifest)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kaine.model_paths import speech_model_dir as model_dir
from kaine.speech_manifest import (
    MANIFEST,
    is_installed,
    validate_tokens_file,
    verify_model_dir,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_marker(
    path: Path,
    model_id: str,
    sha256: str,
    files: dict[str, int],
    tokens_sha256: str | None = None,
) -> None:
    marker = {"model_id": model_id, "sha256": sha256, "files": files}
    if tokens_sha256 is not None:
        marker["tokens_sha256"] = tokens_sha256
    (path / ".verified").write_text(json.dumps(marker), encoding="utf-8")


def _moonshine_install(tmp_path: Path, *, tokens: str = "a 0\nb 1\n") -> tuple[Path, Path]:
    root = tmp_path / "root"
    d = model_dir("moonshine-base-en", root)
    d.mkdir(parents=True)
    (d / "encoder_model.ort").write_bytes(b"enc")
    (d / "decoder_model_merged.ort").write_bytes(b"dec")
    (d / "tokens.txt").write_text(tokens, encoding="utf-8")
    return root, d


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
    with pytest.raises(ValueError, match="not '<token> <id>' or '<id>'"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_negative_id(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("a -1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not '<token> <id>' or '<id>'"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no token"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_three_field_line(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("d Vy 357\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not '<token> <id>' or '<id>'"):
        validate_tokens_file(p)


def test_validate_tokens_file_rejects_second_one_field_line(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("2\n3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not '<token> <id>' or '<id>'"):
        validate_tokens_file(p)


def test_validate_tokens_file_accepts_duplicate_two_field_symbols(tmp_path: Path) -> None:
    p = tmp_path / "tokens.txt"
    p.write_text("a 0\na 1\n", encoding="utf-8")
    validate_tokens_file(p)  # does not raise


def test_verify_model_dir_rejects_missing_marker(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path)
    with pytest.raises(ValueError, match="missing or invalid .verified marker"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_wrong_sha256(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path)
    tokens_sha = _sha256_file(d / "tokens.txt")
    _write_marker(
        d,
        "moonshine-base-en",
        "0000000000000000000000000000000000000000000000000000000000000000",
        {},
        tokens_sha256=tokens_sha,
    )
    with pytest.raises(ValueError, match="marker does not match"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_size_mismatch(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path)
    model = MANIFEST["moonshine-base-en"]
    tokens_sha = _sha256_file(d / "tokens.txt")
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 9999,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 8,
        },
        tokens_sha256=tokens_sha,
    )
    with pytest.raises(ValueError, match="file size mismatch"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_bad_tokens(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path, tokens="bad no int\n")
    model = MANIFEST["moonshine-base-en"]
    tokens_sha = _sha256_file(d / "tokens.txt")
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 3,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 11,
        },
        tokens_sha256=tokens_sha,
    )
    with pytest.raises(ValueError, match="tokens.txt"):
        verify_model_dir("moonshine-base-en", d)


def test_verify_model_dir_rejects_tokens_sha256_mismatch(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path)
    model = MANIFEST["moonshine-base-en"]
    tokens_sha = _sha256_file(d / "tokens.txt")
    (d / "tokens.txt").write_text("x 0\ny 1\n", encoding="utf-8")
    _write_marker(
        d,
        "moonshine-base-en",
        model.sha256,
        {
            "encoder_model.ort": 3,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 8,
        },
        tokens_sha256=tokens_sha,
    )
    with pytest.raises(ValueError, match="tokens.txt digest mismatch"):
        verify_model_dir("moonshine-base-en", d)
    assert is_installed("moonshine-base-en", root) is False


def test_is_installed_false_for_bad_tokens(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path, tokens="\xff")
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
        tokens_sha256=_sha256_file(d / "tokens.txt"),
    )
    assert is_installed("moonshine-base-en", root) is False


def test_is_installed_false_for_marker_without_tokens_sha256(tmp_path: Path) -> None:
    root, d = _moonshine_install(tmp_path)
    model = MANIFEST["moonshine-base-en"]
    marker = {
        "model_id": "moonshine-base-en",
        "sha256": model.sha256,
        "files": {
            "encoder_model.ort": 3,
            "decoder_model_merged.ort": 3,
            "tokens.txt": 8,
        },
    }
    (d / ".verified").write_text(json.dumps(marker), encoding="utf-8")
    assert is_installed("moonshine-base-en", root) is False
    with pytest.raises(ValueError, match="missing tokens_sha256"):
        verify_model_dir("moonshine-base-en", d)
