# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consistency tests for KAINE service definitions.

Checks that images, ports and command-line arguments agree across:
- compose/kaine.yml (canonical stack)
- compose/redis.yml and compose/qdrant.yml (standalone files)
- quadlet/*.container (Podman quadlet units)
- scripts/lib/native-services.sh (native installer)
"""

import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _default(value: object) -> object:
    """Resolve a compose `${NAME:-default}` expression, recursively.

    Strings without a `:-` default (e.g. `${VAR:?error}`) are left unchanged.
    """
    if not isinstance(value, str):
        return value
    text = value
    while True:
        changed = False
        out: list[str] = []
        i = 0
        while i < len(text):
            if text[i] == "$" and i + 1 < len(text) and text[i + 1] == "{":
                # Find the matching '}' using a simple brace counter.
                depth = 1
                j = i + 2
                while j < len(text) and depth > 0:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
                if depth == 0:
                    inner = text[i + 2 : j - 1]
                    # Locate the top-level ':-' separator.
                    sep = -1
                    d = 0
                    for k, ch in enumerate(inner):
                        if ch == "{":
                            d += 1
                        elif ch == "}":
                            d -= 1
                        elif d == 0 and inner.startswith(":-", k):
                            sep = k
                            break
                    if sep >= 0:
                        out.append(_default(inner[sep + 2 :]))
                        i = j
                        changed = True
                        continue
                    # Not a default expansion: keep the original syntax.
                    out.append(text[i:j])
                    i = j
                    continue
            out.append(text[i])
            i += 1
        text = "".join(out)
        if not changed:
            break
    return text


def _norm_image(ref: object) -> object:
    """Drop a leading docker.io/ and then a leading library/."""
    if not isinstance(ref, str):
        return ref
    for prefix in ("docker.io/", "library/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
    return ref


def _quadlet(name: str) -> dict[str, str]:
    """Return single-valued quadlet keys for Image, PublishPort and Exec."""
    path = ROOT / "quadlet" / f"{name}.container"
    text = path.read_text()
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for key in ("Image", "PublishPort", "Exec"):
            if stripped.startswith(f"{key}="):
                result[key] = stripped[len(key) + 1 :]
                break
    return result


def _load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _compose_service(name: str, compose_file: str) -> dict:
    data = _load_compose(ROOT / compose_file)
    return data["services"][name]


def _compose_port(service: dict) -> str:
    ports = service.get("ports", [])
    for p in ports:
        if isinstance(p, str):
            expanded = _default(p)
            if expanded.startswith("127.0.0.1:"):
                return expanded
    raise ValueError("no 127.0.0.1 host port found for service")


def _parse_port(expr: str) -> tuple[str, str]:
    """Return (host_port, container_port) from '127.0.0.1:HOST:CONTAINER'."""
    parts = expr.split(":")
    return parts[1], parts[2]


def _assert_equal(
    service: str,
    aspect: str,
    source_a: str,
    source_b: str,
    a: object,
    b: object,
) -> None:
    if a != b:
        raise AssertionError(
            f"{service} {aspect} mismatch between {source_a} and {source_b}:\n"
            f"  {source_a}: {a!r}\n  {source_b}: {b!r}"
        )


IMAGE_CASES = [
    ("kaine-redis", "compose/kaine.yml", "compose/redis.yml"),
    ("kaine-qdrant", "compose/kaine.yml", "compose/qdrant.yml"),
    ("kaine-model-server", "compose/kaine.yml", None),
    ("kaine-speaches", "compose/kaine.yml", None),
    ("kaine-chatterbox", "compose/kaine.yml", None),
]

PORT_CASES = IMAGE_CASES + [("kaine-nexus", "compose/kaine.yml", None)]


@pytest.mark.parametrize("service, main_file, standalone_file", IMAGE_CASES)
def test_images_agree(service: str, main_file: str, standalone_file: str | None):
    main_image = _norm_image(_default(_compose_service(service, main_file)["image"]))
    quadlet_image = _norm_image(_quadlet(service)["Image"])
    _assert_equal(
        service,
        "image",
        main_file,
        f"quadlet/{service}.container",
        main_image,
        quadlet_image,
    )
    if standalone_file:
        standalone_image = _norm_image(
            _default(_compose_service(service, standalone_file)["image"])
        )
        _assert_equal(
            service,
            "image",
            main_file,
            standalone_file,
            main_image,
            standalone_image,
        )


def test_native_qdrant_version_matches_image():
    native_text = (ROOT / "scripts/lib/native-services.sh").read_text()
    match = re.search(r'^QDRANT_VERSION="([^"]+)"', native_text, re.MULTILINE)
    if not match:
        raise AssertionError("QDRANT_VERSION not found in scripts/lib/native-services.sh")
    native_version = match.group(1)
    image = _norm_image(
        _default(_compose_service("kaine-qdrant", "compose/kaine.yml")["image"])
    )
    image_tag = image.rsplit(":", 1)[1]
    _assert_equal(
        "kaine-qdrant",
        "QDRANT_VERSION",
        "scripts/lib/native-services.sh",
        "compose/kaine.yml image tag",
        native_version,
        image_tag,
    )


@pytest.mark.parametrize("service, main_file, standalone_file", PORT_CASES)
def test_ports_agree(service: str, main_file: str, standalone_file: str | None):
    main_port = _compose_port(_compose_service(service, main_file))
    quadlet_port = _quadlet(service)["PublishPort"]
    _assert_equal(
        service,
        "published port",
        main_file,
        f"quadlet/{service}.container",
        _parse_port(main_port),
        _parse_port(quadlet_port),
    )
    if standalone_file:
        standalone_port = _compose_port(_compose_service(service, standalone_file))
        _assert_equal(
            service,
            "published port",
            main_file,
            standalone_file,
            _parse_port(main_port),
            _parse_port(standalone_port),
        )


def test_redis_command_lists_agree():
    kaine_cmd = _compose_service("kaine-redis", "compose/kaine.yml")["command"]
    standalone_cmd = _compose_service("kaine-redis", "compose/redis.yml")["command"]
    _assert_equal(
        "kaine-redis",
        "command list",
        "compose/kaine.yml",
        "compose/redis.yml",
        kaine_cmd,
        standalone_cmd,
    )


def _normalise_redis_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--requirepass" and i + 1 < len(tokens):
            out.extend([tok, "<password>"])
            i += 2
        elif tok == "--maxmemory" and i + 1 < len(tokens):
            out.extend([tok, "<maxmemory>"])
            i += 2
        else:
            out.append(tok)
            i += 1
    return out


def test_redis_args_compose_matches_quadlet():
    compose_tokens = [
        _default(t) for t in _compose_service("kaine-redis", "compose/kaine.yml")["command"]
    ]
    compose_norm = _normalise_redis_tokens(compose_tokens)
    exec_line = _quadlet("kaine-redis")["Exec"]
    match = re.search(r"exec\s+redis-server\s+(.+?)(?:'|$)", exec_line)
    if not match:
        raise AssertionError(
            "could not locate 'exec redis-server ...' in quadlet/kaine-redis.container"
        )
    quadlet_tokens = ["redis-server", *shlex.split(match.group(1))]
    quadlet_norm = _normalise_redis_tokens(quadlet_tokens)
    _assert_equal(
        "kaine-redis",
        "redis-server args",
        "compose/kaine.yml",
        "quadlet/kaine-redis.container",
        compose_norm,
        quadlet_norm,
    )


def _normalise_model_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--sleep-idle-seconds" and i + 1 < len(tokens):
            out.extend([tok, "<sleep>"])
            i += 2
        elif tok == "-ngl" and i + 1 < len(tokens):
            out.extend([tok, "<ngl>"])
            i += 2
        elif tok == "--cache-ram" and i + 1 < len(tokens):
            out.extend([tok, "<cache-ram>"])
            i += 2
        else:
            out.append(tok)
            i += 1
    return out


def test_model_server_args_agree():
    compose_cmd = _default(
        _compose_service("kaine-model-server", "compose/kaine.yml")["command"]
    )
    compose_tokens = shlex.split(compose_cmd)
    compose_norm = _normalise_model_tokens(compose_tokens)
    exec_line = _quadlet("kaine-model-server")["Exec"]
    match = re.search(r"exec\s+/app/llama-server\s+(.+?)(?:'|$)", exec_line)
    if not match:
        raise AssertionError(
            "could not locate 'exec /app/llama-server ...' in quadlet/kaine-model-server.container"
        )
    quadlet_tokens = shlex.split(match.group(1))
    quadlet_norm = _normalise_model_tokens(quadlet_tokens)
    _assert_equal(
        "kaine-model-server",
        "llama-server args",
        "compose/kaine.yml",
        "quadlet/kaine-model-server.container",
        compose_norm,
        quadlet_norm,
    )
