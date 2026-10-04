# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.lifecycle.individuation_store import Ledger, save_ledger
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_runtime import build
from tests.test_individuation_scheduler import make, write_reference


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _due_ledger() -> Ledger:
    return Ledger(reference_id="r", lived_seconds=10, lived_ticks=10)


async def test_scheduler_adapter_unverifiable_blocks_look_and_capture(
    tmp_path: Path,
):
    sched, core, clock = make(tmp_path, adapter_verifiable=lambda: False)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, _due_ledger())

    await sched.tick()
    clock.t = 1000
    await sched.tick()

    assert sched.state.last_reason == "adapter_unverifiable"
    assert core.looks == []

    sched.request_capture("birth")
    await sched.tick()

    assert core.captures == []


async def test_scheduler_adapter_verifiable_runs_look(tmp_path: Path):
    sched, core, clock = make(tmp_path, adapter_verifiable=lambda: True)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, _due_ledger())

    await sched.tick()
    clock.t = 1000
    await sched.tick()

    assert len(core.looks) == 1


async def test_scheduler_adapter_verifiable_failure_blocks_safely(tmp_path: Path):
    def raise_error() -> bool:
        raise RuntimeError("boom")

    sched, core, clock = make(tmp_path, adapter_verifiable=raise_error)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, _due_ledger())

    await sched.tick()
    clock.t = 1000
    await sched.tick()

    assert sched.state.last_reason == "adapter_unverifiable"
    assert core.looks == []


async def test_runtime_non_per_request_adapter_blocks_when_present(tmp_path: Path):
    adapters = tmp_path / "adapters"
    gen1 = adapters / "gen1"
    gen1.mkdir(parents=True)
    (gen1 / "adapter.gguf").write_bytes(b"weights")
    (adapters / "current").symlink_to(gen1, target_is_directory=True)

    runtime = build(
        tmp_path, per_request_adapter=False, adapter_output_dir=adapters
    )

    assert runtime.scheduler._blocked_reason() == "adapter_unverifiable"

    (adapters / "current").unlink()
    assert runtime.scheduler._blocked_reason() != "adapter_unverifiable"


async def test_runtime_per_request_adapter_does_not_block(tmp_path: Path):
    adapters = tmp_path / "adapters"
    gen1 = adapters / "gen1"
    gen1.mkdir(parents=True)
    (gen1 / "adapter.gguf").write_bytes(b"weights")
    (adapters / "current").symlink_to(gen1, target_is_directory=True)

    runtime = build(
        tmp_path, per_request_adapter=True, adapter_output_dir=adapters
    )

    assert runtime.scheduler._blocked_reason() != "adapter_unverifiable"
