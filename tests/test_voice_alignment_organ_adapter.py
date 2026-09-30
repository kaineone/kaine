# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.modules.hypnos import hot_swap
from kaine.modules.hypnos.organ_adapter import (
    GENERATION,
    MANIFEST,
    OrganAdapterResolver,
    activate,
    organ_root_url,
    read_manifest,
    sha256_file,
    wait_ready,
)
from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient


@pytest.fixture(autouse=True)
def _stub_organ_window():
    sys.modules["kaine.organ_window_state"] = types.SimpleNamespace(
        organ_unloaded=lambda: False
    )
    yield
    sys.modules.pop("kaine.organ_window_state", None)


def _make_own_adapter(adapter_output_dir: Path, content: bytes) -> Path:
    accepted = adapter_output_dir / "accepted-1"
    accepted.mkdir(parents=True)
    (accepted / "adapter.gguf").write_bytes(content)
    current_link = adapter_output_dir / "current"
    current_link.symlink_to(accepted)
    return accepted


def _write_manifest(volume: Path, file: str, sha: str, gen: int) -> dict:
    manifest = {
        "file": file,
        "sha256": sha,
        "generation": gen,
        "adapter_id": "accepted-1",
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    volume.mkdir(parents=True, exist_ok=True)
    (volume / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_activate_writes_first_generation(tmp_path):
    adapter_dir = tmp_path / "accepted" / "my-adapter"
    adapter_dir.mkdir(parents=True)
    source = adapter_dir / "adapter.gguf"
    source.write_bytes(b"gguf-data")
    volume = tmp_path / "organ"

    manifest = activate(adapter_dir, volume)

    assert (volume / "active-1.gguf").is_file()
    assert manifest["file"] == "active-1.gguf"
    assert manifest["sha256"] == sha256_file(source)
    assert manifest["generation"] == 1
    assert manifest["adapter_id"] == "my-adapter"
    assert "activated_at" in manifest
    assert json.loads((volume / MANIFEST).read_text(encoding="utf-8")) == manifest
    assert (volume / GENERATION).read_text(encoding="utf-8") == "1"
    assert (volume / "active-1.gguf").stat().st_mode & 0o777 == 0o644


def test_activate_bumps_generation_and_prunes(tmp_path):
    adapter_dir = tmp_path / "a" / "adapter"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter.gguf").write_bytes(b"v1")
    volume = tmp_path / "vol"

    m1 = activate(adapter_dir, volume)
    assert m1["generation"] == 1

    (adapter_dir / "adapter.gguf").write_bytes(b"v2")
    m2 = activate(adapter_dir, volume)
    assert m2["generation"] == 2
    assert (volume / "active-1.gguf").exists()
    assert (volume / "active-2.gguf").exists()

    (adapter_dir / "adapter.gguf").write_bytes(b"v3")
    m3 = activate(adapter_dir, volume)
    assert m3["generation"] == 3
    assert not (volume / "active-1.gguf").exists()
    assert (volume / "active-2.gguf").exists()
    assert (volume / "active-3.gguf").exists()
    assert (volume / GENERATION).read_text(encoding="utf-8") == "3"


def test_activate_writes_generation_after_manifest(monkeypatch, tmp_path):
    adapter_dir = tmp_path / "a"
    adapter_dir.mkdir()
    (adapter_dir / "adapter.gguf").write_bytes(b"x")
    volume = tmp_path / "vol"

    order = []
    real_replace = os.replace

    def fake_replace(src, dst):
        order.append(Path(dst).name)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fake_replace)
    activate(adapter_dir, volume)

    assert order[-2] == "active.json"
    assert order[-1] == GENERATION


def test_activate_rejects_symlink_source(tmp_path):
    adapter_dir = tmp_path / "a"
    adapter_dir.mkdir()
    real_file = tmp_path / "real.gguf"
    real_file.write_bytes(b"x")
    link = adapter_dir / "adapter.gguf"
    link.symlink_to(real_file)

    with pytest.raises(ValueError):
        activate(adapter_dir, tmp_path / "vol")


@pytest.mark.parametrize(
    "payload",
    [
        {"file": "../x.gguf", "sha256": "a" * 64, "generation": 1, "adapter_id": "x"},
        {"file": "active-1.gguf", "sha256": "nothex", "generation": 1, "adapter_id": "x"},
        {"file": "active-1.gguf", "sha256": "a" * 64, "generation": 0, "adapter_id": "x"},
        "not a dict",
        {"file": "active-1.gguf", "sha256": "a" * 64, "generation": 1},
    ],
)
def test_read_manifest_rejects_invalid(payload, tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    (volume / MANIFEST).write_text(json.dumps(payload), encoding="utf-8")
    assert read_manifest(volume) is None


@pytest.mark.asyncio
async def test_wait_ready_eventually_true():
    calls = []

    async def getter(url, headers):
        calls.append(None)
        if len(calls) < 3:
            return 200, [{"path": "/x/active-1.gguf", "id": 1}]
        return 200, [{"path": "/x/active-2.gguf", "id": 2}]

    clock = [0.0]

    async def fake_sleep(_):
        clock[0] += 2.0

    ready = await wait_ready(
        "http://organ",
        "active-2.gguf",
        http_get=getter,
        sleep=fake_sleep,
        clock=lambda: clock[0],
        timeout_s=10.0,
        poll_s=2.0,
    )
    assert ready is True
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_wait_ready_times_out():
    async def getter(url, headers):
        return 200, []

    clock = [0.0]

    async def fake_sleep(_):
        clock[0] += 2.0

    ready = await wait_ready(
        "http://organ",
        "active-1.gguf",
        http_get=getter,
        sleep=fake_sleep,
        clock=lambda: clock[0],
        timeout_s=5.0,
        poll_s=2.0,
    )
    assert ready is False


@pytest.mark.asyncio
async def test_wait_ready_non_200_keeps_polling():
    calls = []

    async def getter(url, headers):
        calls.append(None)
        if len(calls) < 3:
            return 500, None
        return 200, [{"path": "/x/active-1.gguf", "id": 1}]

    clock = [0.0]

    async def fake_sleep(_):
        clock[0] += 2.0

    ready = await wait_ready(
        "http://organ",
        "active-1.gguf",
        http_get=getter,
        sleep=fake_sleep,
        clock=lambda: clock[0],
        timeout_s=10.0,
        poll_s=2.0,
    )
    assert ready is True
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_resolver_applies_when_sha_and_file_match(tmp_path):
    adapter_output_dir = tmp_path / "out"
    volume = tmp_path / "organ"
    accepted = _make_own_adapter(adapter_output_dir, b"my-adapter")
    sha = sha256_file(accepted / "adapter.gguf")
    _write_manifest(volume, "active-3.gguf", sha, 3)

    async def getter(url, headers):
        return 200, [{"path": "/organ-adapters/active-3.gguf", "id": 3}]

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=volume,
        organ_url="http://organ",
        api_key=None,
        http_get=getter,
        ttl_s=60.0,
    )
    field = await resolver.lora_field()
    assert field == [{"id": 3, "scale": 1.0}]


@pytest.mark.asyncio
async def test_resolver_none_when_sha_mismatch(tmp_path):
    adapter_output_dir = tmp_path / "out"
    volume = tmp_path / "organ"
    _make_own_adapter(adapter_output_dir, b"my-adapter")
    _write_manifest(volume, "active-3.gguf", "b" * 64, 3)

    async def getter(url, headers):
        return 200, [{"path": "/organ-adapters/active-3.gguf", "id": 3}]

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=volume,
        organ_url="http://organ",
        api_key=None,
        http_get=getter,
        ttl_s=60.0,
    )
    assert await resolver.lora_field() is None


@pytest.mark.asyncio
async def test_resolver_none_when_organ_lists_older_file(tmp_path):
    adapter_output_dir = tmp_path / "out"
    volume = tmp_path / "organ"
    accepted = _make_own_adapter(adapter_output_dir, b"my-adapter")
    sha = sha256_file(accepted / "adapter.gguf")
    _write_manifest(volume, "active-2.gguf", sha, 2)

    async def getter(url, headers):
        return 200, [{"path": "/organ-adapters/active-1.gguf", "id": 1}]

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=volume,
        organ_url="http://organ",
        api_key=None,
        http_get=getter,
        ttl_s=60.0,
    )
    assert await resolver.lora_field() is None


@pytest.mark.asyncio
async def test_resolver_none_when_no_manifest(tmp_path):
    resolver = OrganAdapterResolver(
        adapter_output_dir=tmp_path / "out",
        volume=tmp_path / "organ",
        organ_url="http://organ",
        api_key=None,
        http_get=None,
        ttl_s=60.0,
    )
    assert await resolver.lora_field() is None


@pytest.mark.asyncio
async def test_resolver_none_when_organ_get_errors(tmp_path):
    adapter_output_dir = tmp_path / "out"
    volume = tmp_path / "organ"
    accepted = _make_own_adapter(adapter_output_dir, b"my-adapter")
    sha = sha256_file(accepted / "adapter.gguf")
    _write_manifest(volume, "active-1.gguf", sha, 1)

    async def getter(url, headers):
        raise RuntimeError("boom")

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=volume,
        organ_url="http://organ",
        api_key=None,
        http_get=getter,
        ttl_s=60.0,
    )
    assert await resolver.lora_field() is None


@pytest.mark.asyncio
async def test_resolver_caches_lora_adapters(tmp_path):
    adapter_output_dir = tmp_path / "out"
    volume = tmp_path / "organ"
    accepted = _make_own_adapter(adapter_output_dir, b"my-adapter")
    sha = sha256_file(accepted / "adapter.gguf")
    _write_manifest(volume, "active-1.gguf", sha, 1)

    calls = []

    async def getter(url, headers):
        calls.append(None)
        return 200, [{"path": "/organ-adapters/active-1.gguf", "id": 1}]

    clock = [0.0]
    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=volume,
        organ_url="http://organ",
        api_key=None,
        http_get=getter,
        ttl_s=10.0,
        clock=lambda: clock[0],
    )

    assert await resolver.lora_field() == [{"id": 1, "scale": 1.0}]
    clock[0] += 1.0
    assert await resolver.lora_field() == [{"id": 1, "scale": 1.0}]
    assert len(calls) == 1


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def _make_fake_client(captured):
    class FakeClient:
        async def post(self, url, *, json):
            captured.append(json)
            return _FakeResponse(
                json_data={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {},
                    "model": "m",
                }
            )

        async def aclose(self):
            pass

    return FakeClient()


def _resolver_returning(field):
    class R:
        async def lora_field(self):
            return field

    return R()


@pytest.mark.asyncio
async def test_client_adds_lora_field(monkeypatch):
    client = OpenAIChatClient(lora_resolver=_resolver_returning([{"id": 7, "scale": 1.0}]))
    captured = []
    monkeypatch.setattr(client, "_ensure_client", lambda: _make_fake_client(captured))

    await client.complete(ChatRequest(prompt="hi", model="m", think=None))
    assert "lora" in captured[0]
    assert captured[0]["lora"] == [{"id": 7, "scale": 1.0}]


@pytest.mark.asyncio
async def test_client_omits_lora_when_resolver_returns_none(monkeypatch):
    client = OpenAIChatClient(lora_resolver=_resolver_returning(None))
    captured = []
    monkeypatch.setattr(client, "_ensure_client", lambda: _make_fake_client(captured))

    await client.complete(ChatRequest(prompt="hi", model="m", think=None))
    assert "lora" not in captured[0]


@pytest.mark.asyncio
async def test_client_sends_without_lora_when_resolver_raises(monkeypatch, caplog):
    class BadResolver:
        async def lora_field(self):
            raise RuntimeError("nope")

    client = OpenAIChatClient(lora_resolver=BadResolver())
    captured = []
    monkeypatch.setattr(client, "_ensure_client", lambda: _make_fake_client(captured))

    await client.complete(ChatRequest(prompt="hi", model="m", think=None))
    assert "lora" not in captured[0]
    assert "lora resolver failed" in caplog.text


@pytest.mark.asyncio
async def test_dispatch_organ_adapter_ready(monkeypatch, tmp_path):
    adapter_path = tmp_path / "accepted" / "adapter"
    adapter_path.mkdir(parents=True)

    monkeypatch.setattr(
        hot_swap,
        "activate",
        lambda p, v: {"file": "active-1.gguf", "generation": 1},
    )

    async def fake_wait(*args, **kwargs):
        return True

    monkeypatch.setattr(hot_swap, "wait_ready", fake_wait)

    result = await hot_swap.dispatch(
        mode="organ_adapter",
        adapter_output_dir=tmp_path / "out",
        adapter_path=adapter_path,
        organ_adapters_dir=tmp_path / "organ",
        organ_url="http://organ/v1",
    )

    assert result["mode"] == "organ_adapter"
    assert result["ok"] is True
    assert result["generation"] == 1
    assert result["file"] == "active-1.gguf"


@pytest.mark.asyncio
async def test_dispatch_organ_adapter_timeout(monkeypatch, tmp_path):
    adapter_path = tmp_path / "accepted" / "adapter"
    adapter_path.mkdir(parents=True)

    monkeypatch.setattr(
        hot_swap,
        "activate",
        lambda p, v: {"file": "active-1.gguf", "generation": 1},
    )

    async def fake_wait(*args, **kwargs):
        return False

    monkeypatch.setattr(hot_swap, "wait_ready", fake_wait)

    result = await hot_swap.dispatch(
        mode="organ_adapter",
        adapter_output_dir=tmp_path / "out",
        adapter_path=adapter_path,
        organ_adapters_dir=tmp_path / "organ",
        organ_url="http://organ/v1",
        organ_wait_s=5.0,
    )

    assert result["ok"] is False
    assert "5 s" in result["error"]


@pytest.mark.asyncio
async def test_dispatch_organ_adapter_missing_dir(tmp_path):
    adapter_path = tmp_path / "accepted" / "adapter"
    adapter_path.mkdir(parents=True)

    result = await hot_swap.dispatch(
        mode="organ_adapter",
        adapter_output_dir=tmp_path / "out",
        adapter_path=adapter_path,
        organ_adapters_dir=None,
        organ_url="http://organ/v1",
    )

    assert result["ok"] is False
    assert "organ_adapters_dir" in result["error"]


class _FakeRegistry:
    def __init__(self, lingua, hypnos):
        self._mods = {"lingua": lingua, "hypnos": hypnos}

    def __contains__(self, key):
        return key in self._mods

    def get(self, key):
        return self._mods[key]


class _FakeLingua:
    def __init__(self):
        self.calls = []

    def set_lora_resolver(self, resolver):
        self.calls.append(resolver)


def _make_wiring_config(tmp_path, mode, shared=False):
    cfg = {
        "hypnos": {
            "voice_alignment": {
                "enabled": True,
                "hot_swap_mode": mode,
                "adapter_output_dir": str(tmp_path / "adapters"),
                "organ_adapters_dir": str(tmp_path / "organ"),
                "organ_url": "http://organ/v1",
            }
        },
        "lingua": {"chat_url": "http://chat/v1", "api_key": "secret"},
    }
    if shared:
        cfg["services"] = {"model_server": {"shared": True}}
    return cfg


def test_wire_lingua_organ_adapter_sets_resolver(tmp_path):
    from kaine.boot import _wire_lingua_organ_adapter

    lingua = _FakeLingua()
    reg = _FakeRegistry(lingua, object())
    cfg = _make_wiring_config(tmp_path, "organ_adapter")

    _wire_lingua_organ_adapter(reg, cfg)

    assert len(lingua.calls) == 1
    assert isinstance(lingua.calls[0], OrganAdapterResolver)


def test_wire_lingua_organ_adapter_manual_mode_no_resolver(tmp_path):
    from kaine.boot import _wire_lingua_organ_adapter

    lingua = _FakeLingua()
    reg = _FakeRegistry(lingua, object())
    cfg = _make_wiring_config(tmp_path, "manual")

    _wire_lingua_organ_adapter(reg, cfg)

    assert len(lingua.calls) == 0


def test_wire_lingua_organ_adapter_shared_model_server_no_resolver(tmp_path):
    from kaine.boot import _wire_lingua_organ_adapter

    lingua = _FakeLingua()
    reg = _FakeRegistry(lingua, object())
    cfg = _make_wiring_config(tmp_path, "organ_adapter", shared=True)

    _wire_lingua_organ_adapter(reg, cfg)

    assert len(lingua.calls) == 0


def test_organ_root_url():
    assert organ_root_url("http://organ/v1") == "http://organ"
    assert organ_root_url("http://organ/v1/") == "http://organ"
    assert organ_root_url("http://organ/") == "http://organ"
    assert organ_root_url("http://organ") == "http://organ"
