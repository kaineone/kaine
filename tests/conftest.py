# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os

import pytest

from kaine.bus import reset_bus_for_tests
from kaine.bus.config import BusConfig


@pytest.fixture(autouse=True)
def _reset_bus_singleton():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


@pytest.fixture(autouse=True)
def _save_restore_state_encryptor():
    """Save and restore the process-global state encryptor around each test."""
    from kaine.security import crypto as crypto_module

    previous = getattr(crypto_module, "_active", None)
    yield
    crypto_module._active = previous


@pytest.fixture(autouse=True)
def _save_restore_data_root(tmp_path, monkeypatch, request):
    """Save and restore the process-wide data root around each test, so a test
    that installs one cannot redirect later tests' relative state paths."""
    from kaine import storage

    previous = storage.data_root()
    if request.node.get_closest_marker("no_data_root") is None:
        # Each test starts with its own data root, so any relative state/ path
        # a module resolves lands in the test's tmp directory, never in the
        # repository. KAINE_DATA_ROOT keeps it when an entry point reinstalls
        # the root from config. A test may still install or clear its own;
        # tests of the no-root defaults carry @pytest.mark.no_data_root.
        storage.set_data_root(tmp_path)
        monkeypatch.setenv(storage.DATA_ROOT_ENV, str(tmp_path))
    yield
    storage.set_data_root(previous)


@pytest.fixture(autouse=True)
def _isolate_stage_file(tmp_path, monkeypatch):
    """Point the default developmental-stage file at this test's tmp_path.

    The stage file decides gestation versus embodiment at boot. A test that
    saves a stage without naming a path must never write the real
    ``state/lifecycle/stage.json`` of the checkout (or of whatever data root is
    installed). A test that sets ``STAGE_PATH`` itself still overrides this.
    """
    monkeypatch.setattr(
        "kaine.lifecycle.stage.STAGE_PATH",
        tmp_path / "isolated-state" / "lifecycle" / "stage.json",
    )


_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_STATE = os.path.join(_REPO, "state")
# Large or operator-owned trees no test may touch anyway; skipping them keeps
# the per-test check cheap. Preserved beings live in state/forks.
_STATE_SKIP = {"models", "forks"}


def _state_fingerprint() -> dict[str, int]:
    """Directory mtimes under the repo's state/: any file a test creates,
    renames or deletes there changes one of them."""
    marks: dict[str, int] = {}
    if not os.path.isdir(_REPO_STATE):
        return marks
    for root, dirs, _files in os.walk(_REPO_STATE):
        if root == _REPO_STATE:
            dirs[:] = [d for d in dirs if d not in _STATE_SKIP and not d.startswith("_archive")]
        marks[root] = os.stat(root).st_mtime_ns
    return marks


@pytest.fixture(autouse=True)
def _repo_state_untouched():
    """Fail any test that writes into the repository's own state/ directory.

    A stray stage file, perception desired-state or consolidation record there
    is read at the next spawn from this checkout: it can mark a fresh being as
    already lived, or hand it a test's developmental stage.
    """
    before = _state_fingerprint()
    yield
    after = _state_fingerprint()
    if after != before:
        changed = sorted(set(after.items()) ^ set(before.items()))
        dirs = sorted({path for path, _ in changed})
        pytest.fail(
            "test wrote into the repository's state/ (use tmp_path or monkeypatch "
            f"the default path): {dirs}"
        )


@pytest.fixture
def bus_config_with_password() -> BusConfig:
    return BusConfig(password="test-password", audit_required=False)


@pytest.fixture
async def fake_async_bus(bus_config_with_password):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    # Same pool size as the production bus client (redis-py 8 caps an unset
    # pool at 100).
    client = fakeredis.FakeRedis(
        decode_responses=True, max_connections=BusConfig().max_connections
    )
    from kaine.bus.client import AsyncBus
    bus = AsyncBus(bus_config_with_password, client=client)
    yield bus
    await bus.close()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("KAINE_REDIS_PASSWORD"):
        return
    skip_integration = pytest.mark.skip(
        reason="KAINE_REDIS_PASSWORD not set; integration tests need authenticated Redis"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
