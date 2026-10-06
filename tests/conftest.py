# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import warnings

import pytest

from kaine.bus import reset_bus_for_tests
from kaine.bus.config import BusConfig
from kaine.config import load_kaine_config
from kaine.lifecycle.liveness import cycle_process_state
from kaine.setup import storage_step
from kaine.storage import configured_data_root


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


def _is_inside_repo(path: str) -> bool:
    """Return True if ``path`` is the repository directory or under it."""
    if not path:
        return False
    real = os.path.realpath(path)
    repo_real = os.path.realpath(_REPO)
    return real == repo_real or real.startswith(repo_real + os.sep)


def _state_fingerprint(state_root: str) -> dict[str, int]:
    """Directory mtimes under ``state_root``: any file creation, rename or
    deletion in a watched directory changes one of them. Never reads file
    contents.
    """
    marks: dict[str, int] = {}
    if not os.path.isdir(state_root):
        return marks
    for root, dirs, _files in os.walk(state_root):
        if root == state_root:
            dirs[:] = [
                d
                for d in dirs
                if d not in _STATE_SKIP and not d.startswith("_archive")
            ]
        marks[root] = os.stat(root).st_mtime_ns
    return marks


def _changed_dirs(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Return the directory paths whose mtimes changed between two snapshots."""
    changed = sorted(set(after.items()) ^ set(before.items()))
    return sorted({path for path, _ in changed})


def _compute_real_state_roots() -> list[str]:
    """Return the state/ directories of real KAINE data roots known at session
    start, excluding the repository and any path that is not a directory.
    """
    candidates: set[str] = set()

    try:
        config = load_kaine_config()
        cfg_root = configured_data_root(config, os.environ)
    except Exception:
        cfg_root = None

    if cfg_root is not None:
        path = str(cfg_root)
        if os.path.isabs(path) and os.path.isdir(path):
            real = os.path.realpath(path)
            if not _is_inside_repo(real):
                candidates.add(real)

    try:
        recommended = storage_step.recommend_root(storage_step.list_filesystems())
    except Exception:
        recommended = None

    if recommended is not None:
        path = str(recommended)
        if os.path.isdir(path):
            real = os.path.realpath(path)
            if not _is_inside_repo(real):
                candidates.add(real)

    state_roots: list[str] = []
    for root in candidates:
        state_dir = os.path.join(root, "state")
        if os.path.isdir(state_dir):
            state_roots.append(os.path.realpath(state_dir))

    return sorted(set(state_roots))


try:
    _CYCLE_RUNNING = cycle_process_state()
except Exception:
    _CYCLE_RUNNING = None

if _CYCLE_RUNNING is not False:
    warnings.warn(
        "Real KAINE data-root guard is disabled: a kaine.cycle process appears "
        "to be running, or the process list could not be read. Tests may "
        "legitimately write to a live data root.",
        stacklevel=2,
    )
    _REAL_STATE_ROOTS: list[str] = []
else:
    _REAL_STATE_ROOTS = _compute_real_state_roots()


@pytest.fixture(autouse=True)
def _no_real_mounts(tmp_path, monkeypatch, request):
    """Point the storage wizard at an empty mounts file so it cannot propose a
    real disk as the data root. Tests of mount parsing opt out with
    @pytest.mark.real_mounts and supply their own file, as today.
    """
    if request.node.get_closest_marker("real_mounts") is None:
        empty_mounts = tmp_path / "no-mounts"
        empty_mounts.write_text("")
        monkeypatch.setattr("kaine.setup.storage_step.MOUNTS_PATH", empty_mounts)
    yield


@pytest.fixture(autouse=True)
def _repo_state_untouched():
    """Fail any test that writes into the repository's own state/ directory.

    A stray stage file, perception desired-state or consolidation record there
    is read at the next spawn from this checkout: it can mark a fresh being as
    already lived, or hand it a test's developmental stage.
    """
    before = _state_fingerprint(_REPO_STATE)
    yield
    after = _state_fingerprint(_REPO_STATE)
    changed = _changed_dirs(before, after)
    if changed:
        pytest.fail(
            "test wrote into the repository's state/ (use tmp_path or monkeypatch "
            f"the default path): {changed}"
        )


@pytest.fixture(autouse=True)
def _real_data_untouched():
    """Fail any test that writes into a real KAINE data root known at session
    start. Disabled while a kaine.cycle process may be writing to those roots.
    """
    if not _REAL_STATE_ROOTS:
        yield
        return
    before = {root: _state_fingerprint(root) for root in _REAL_STATE_ROOTS}
    yield
    after = {root: _state_fingerprint(root) for root in _REAL_STATE_ROOTS}
    changed: list[str] = []
    for root in _REAL_STATE_ROOTS:
        changed.extend(_changed_dirs(before[root], after[root]))
    if changed:
        pytest.fail(
            "test wrote into a real KAINE data root (use tmp_path or the "
            f"per-test data root): {sorted(set(changed))}"
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
