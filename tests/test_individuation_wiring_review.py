# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from kaine.lifecycle.individuation_store import adapter_sha_of
from kaine.modules.hypnos import organ_adapter
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_runtime import (
    _make_reference,
    build,
    save_reference,
)


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def test_adapter_sha_caches_per_file(tmp_path: Path, monkeypatch):
    adapters = tmp_path / "adapters"
    gen1 = adapters / "gen1"
    gen1.mkdir(parents=True)
    (gen1 / "adapter.gguf").write_bytes(b"weights-1")
    (adapters / "current").symlink_to(gen1, target_is_directory=True)

    calls: list[Path] = []
    orig_sha = organ_adapter.sha256_file

    def counting_sha(path: Path) -> str:
        calls.append(path)
        return orig_sha(path)

    monkeypatch.setattr(organ_adapter, "sha256_file", counting_sha)

    assert adapter_sha_of(adapters) is not None
    assert adapter_sha_of(adapters) is not None
    assert len(calls) == 1

    (gen1 / "adapter.gguf").write_bytes(b"weights-2-are-different")
    later = time.time() + 1000
    os.utime(gen1 / "adapter.gguf", (later, later))

    assert adapter_sha_of(adapters) is not None
    assert len(calls) == 2


def test_runtime_adapter_rule_does_not_hash(tmp_path: Path, monkeypatch):
    adapters = tmp_path / "adapters"
    gen1 = adapters / "gen1"
    gen1.mkdir(parents=True)
    (gen1 / "adapter.gguf").write_bytes(b"weights")
    (adapters / "current").symlink_to(gen1, target_is_directory=True)

    def raise_if_hashed(path: Path) -> str:
        raise AssertionError("sha256_file must not be called by the adapter rule")

    monkeypatch.setattr(organ_adapter, "sha256_file", raise_if_hashed)

    runtime = build(
        tmp_path, per_request_adapter=False, adapter_output_dir=adapters
    )
    assert runtime.scheduler._blocked_reason() == "adapter_unverifiable"


async def test_birth_marker_survives_restart(tmp_path: Path):
    runtime = build(tmp_path, is_gestating=lambda: False)
    runtime.on_birth()
    assert runtime.paths.birth_pending.exists()

    runtime2 = build(tmp_path, is_gestating=lambda: False)
    await runtime2.start()
    assert runtime2.scheduler._capture_kind == "birth"


def test_sleep_clears_birth_marker(tmp_path: Path):
    runtime = build(tmp_path, is_gestating=lambda: False)
    runtime.on_birth()
    assert runtime.paths.birth_pending.exists()
    assert runtime.scheduler._capture_kind == "birth"

    runtime.scheduler.notify_sleep_completed()
    assert runtime.scheduler._capture_kind == "capture"
    assert not runtime.paths.birth_pending.exists()


async def test_existing_reference_removes_stale_marker(tmp_path: Path):
    runtime = build(tmp_path)
    paths = runtime.paths
    paths.root.mkdir(parents=True, exist_ok=True)
    doc = _make_reference(paths, "ref-1")
    save_reference(paths, doc)
    paths.birth_pending.write_text("1", encoding="utf-8")
    assert paths.birth_pending.exists()

    runtime2 = build(tmp_path, is_gestating=lambda: False)
    await runtime2.start()
    assert not runtime2.paths.birth_pending.exists()
    assert runtime2.scheduler._capture_kind is None


async def test_start_does_not_override_pending_birth(tmp_path: Path):
    runtime = build(tmp_path, is_gestating=lambda: False)
    runtime.on_birth()
    await runtime.start()
    assert runtime.scheduler._capture_kind == "birth"
    assert runtime.paths.birth_pending.exists()


async def test_start_keeps_a_pending_birth_request_without_a_marker(tmp_path: Path):
    # As when writing the marker failed: the in-memory request still wins.
    runtime = build(tmp_path, is_gestating=lambda: False)
    runtime.scheduler.request_capture("birth")
    assert not runtime.paths.birth_pending.exists()
    await runtime.start()
    assert runtime.scheduler._capture_kind == "birth"
