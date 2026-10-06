# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verify the llama.cpp model-server image and flags are pinned and explicit."""

import re
import shlex
from pathlib import Path

import pytest
import yaml

PINNED_BUILD = "b11382"
LLAMA_CPP_SHA256 = (
    "ec72df2bfc334138cabd54ef77211882040827639e8caf17bc1648fe0b9ffdab"
)

_CUDA_DIGEST = (
    "ghcr.io/ggml-org/llama.cpp@sha256:"
    "ef08b5a98b1170f2b62177be0a4027c88a84043c55afbf190dd18b9e7cdcfebf"
)
_ROCM_DIGEST = (
    "ghcr.io/ggml-org/llama.cpp@sha256:"
    "46583bd112bf2d62881d6aeaae52e59238d61cbf5803296521cdf518548016e6"
)
_CPU_DIGEST = (
    "ghcr.io/ggml-org/llama.cpp@sha256:"
    "559ac229adefe0f7e2d4e32f5222f26927b6bb8ba44b9db08e2544afebf41984"
)

_DIGEST_RE = re.compile(r"^ghcr\.io/ggml-org/llama\.cpp@sha256:[0-9a-f]{64}$")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_image_ref(image_expr: str) -> str:
    m = re.fullmatch(r"\$\{KAINE_MODEL_SERVER_IMAGE:-([^}]+)\}", image_expr)
    assert m, f"unexpected image expression: {image_expr!r}"
    return m.group(1)


@pytest.mark.parametrize(
    ("compose_file", "expected_digest"),
    [
        ("compose/kaine.yml", _CUDA_DIGEST),
        ("compose/kaine.rocm.yml", _ROCM_DIGEST),
        ("compose/kaine.cpu.yml", _CPU_DIGEST),
    ],
)
def test_compose_model_server_image_is_pinned(compose_file, expected_digest):
    path = REPO_ROOT / compose_file
    data = yaml.safe_load(path.read_text())
    digest = _default_image_ref(data["services"]["kaine-model-server"]["image"])
    assert _DIGEST_RE.match(digest)
    assert digest == expected_digest
    assert f"llama.cpp build {PINNED_BUILD}" in path.read_text()


def test_quadlet_model_server_image_is_pinned():
    path = REPO_ROOT / "quadlet" / "kaine-model-server.container"
    text = path.read_text()
    m = re.search(r"^Image=(.+)$", text, re.MULTILINE)
    assert m
    digest = m.group(1)
    assert _DIGEST_RE.match(digest)
    assert digest == _CUDA_DIGEST
    assert f"llama.cpp build {PINNED_BUILD}" in text


def test_dockerfile_converter_is_pinned():
    path = REPO_ROOT / "Dockerfile"
    text = path.read_text()
    tag_m = re.search(r"^ARG LLAMA_CPP_TAG=(\S+)$", text, re.MULTILINE)
    sha_m = re.search(r"^ARG LLAMA_CPP_SHA256=(\S+)$", text, re.MULTILINE)
    assert tag_m and tag_m.group(1) == PINNED_BUILD
    assert sha_m and sha_m.group(1) == LLAMA_CPP_SHA256


def _value_after(tokens: list[str], flag: str) -> str:
    assert tokens.count(flag) == 1, f"{flag} must appear exactly once in {tokens}"
    i = tokens.index(flag)
    assert i + 1 < len(tokens), f"{flag} has no value"
    return tokens[i + 1].strip('"')


def _assert_flag_pairs(tokens: list[str]) -> None:
    """Each explicit setting is a flag followed by the right value, not just
    both tokens appearing somewhere on the line."""
    assert _value_after(tokens, "--fit") == "off"
    assert _value_after(tokens, "-ctk") == "f16"
    assert _value_after(tokens, "-ctv") == "f16"
    ngl = _value_after(tokens, "-ngl")
    cram = _value_after(tokens, "--cache-ram")
    for name, value in (("-ngl", ngl), ("--cache-ram", cram)):
        assert value.isdigit() or value.startswith("${") or value.startswith("$$"), (
            f"{name} value {value!r} is neither a number nor the validated variable"
        )


def test_compose_command_has_explicit_model_server_flags():
    path = REPO_ROOT / "compose" / "kaine.yml"
    data = yaml.safe_load(path.read_text())
    cmd = data["services"]["kaine-model-server"]["command"]
    m = re.search(r"\$\{KAINE_MODEL_SERVER_CMD:-(.+)\}$", cmd, re.DOTALL)
    assert m, f"unexpected command expression: {cmd!r}"
    default = m.group(1)
    _assert_flag_pairs(default.split())


def test_quadlet_exec_has_explicit_model_server_flags():
    path = REPO_ROOT / "quadlet" / "kaine-model-server.container"
    text = path.read_text()
    m = re.search(r"exec\s+/app/llama-server\s+(.+?)'", text)
    assert m, "could not locate the llama-server exec in the quadlet"
    _assert_flag_pairs(shlex.split(m.group(1)))

def test_no_slot_save_path_committed():
    paths = [
        REPO_ROOT / "compose" / "kaine.yml",
        REPO_ROOT / "compose" / "kaine.rocm.yml",
        REPO_ROOT / "compose" / "kaine.cpu.yml",
        REPO_ROOT / "quadlet" / "kaine-model-server.container",
        REPO_ROOT / "docker" / "organ-launcher.sh",
    ]
    for path in paths:
        text = path.read_text()
        assert "--slot-save-path" not in text, f"{path} contains --slot-save-path"
        assert "slot-save" not in text, f"{path} contains slot-save"
