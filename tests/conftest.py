# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import stat
import warnings

import pytest

from kaine.bus import reset_bus_for_tests
from kaine.bus.config import BusConfig
from kaine.config import load_kaine_config
from kaine.lifecycle.liveness import cycle_process_state
from kaine.setup import storage_step
from kaine.storage import configured_data_root

# Real OS primitives captured at import time so that data-root guards keep
# working while a test monkeypatches os.stat/os.scandir.
_REAL_SCANDIR = os.scandir
_REAL_STAT = os.stat


def _REAL_ISDIR(path: str) -> bool:
    """``os.path.isdir`` built on the captured ``os.stat``: the stdlib version
    looks ``os.stat`` up at call time, so a test's patch would reach it."""
    try:
        return stat.S_ISDIR(_REAL_STAT(path).st_mode)
    except (OSError, ValueError):
        return False

# Fixtures shared by the trainer tests (the fake training stack) are registered
# here so test modules can request them by name.
pytest_plugins = ["tests.fake_training_stack"]


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
# The checkout's config/ holds the operator's real secrets.toml and
# kaine.operator.toml; a test must never create or change a file there.
_REPO_CONFIG = os.path.join(_REPO, "config")

# In state/, forks and models are watched shallowly (rule 2): the directory
# and its immediate children are fingerprinted, but their contents are not
# walked.  _archive* directories are fully skipped.
_STATE_SKIP = frozenset({"forks", "models"})

# Operator-owned tooling/cache directories at the top of a real data root.
# Entity data must never go in this list; the default is to watch.
_REAL_ROOT_SKIP = frozenset(
    {"models", "build-cache", "scratch", "abliteration", "_nonresearch_artifacts"}
)
_REAL_ROOT_SKIP_PREFIXES = ("k1jev",)


def _is_inside_repo(path: str) -> bool:
    """Return True if ``path`` is the repository directory, under it, or
    contains it.  Any of those cases means the path is not an independent
    real KAINE data root.
    """
    if not path:
        return False
    real = os.path.realpath(path)
    repo_real = os.path.realpath(_REPO)
    if real == repo_real or real.startswith(repo_real + os.sep):
        return True
    if repo_real.startswith(real + os.sep):
        return True
    return False


def _fingerprint(
    root: str,
    skip_names: set[str] | frozenset[str],
    full_skip_names: set[str] | frozenset[str] = frozenset(),
    full_skip_prefixes: tuple[str, ...] = (),
) -> dict[str, tuple[int, int]]:
    """Return ``{path: (st_mtime_ns, st_size)}`` for every directory and
    regular file under ``root``.

    Uses import-time OS primitives and ``DirEntry`` methods so a test's
    monkeypatch of ``os.stat``/``os.scandir`` does not affect the guard.  Never
    opens or reads file contents.

    Directories whose names are in ``skip_names`` are handled with rule 2:
    the directory itself and its immediate children are recorded, but the
    guard does not recurse into them.

    ``full_skip_names``/``full_skip_prefixes`` are applied at the root's top
    level (and the top level of a ``state/`` child of the root); matching
    subtrees are omitted entirely.  ``_archive*`` directories are always
    fully skipped at those top levels.
    """
    marks: dict[str, tuple[int, int]] = {}
    if not _REAL_ISDIR(root):
        return marks
    try:
        st = _REAL_STAT(root)
        marks[root] = (st.st_mtime_ns, st.st_size)
    except OSError:
        return marks

    state_dir = os.path.join(root, "state")
    stack: list[str] = [root]
    while stack:
        current = stack.pop()
        at_root_top = current == root
        at_state_top = at_root_top or current == state_dir

        try:
            with _REAL_SCANDIR(current) as it:
                for entry in it:
                    if at_root_top:
                        if (
                            entry.name in full_skip_names
                            or any(entry.name.startswith(p) for p in full_skip_prefixes)
                        ):
                            continue
                    if at_state_top and entry.name.startswith("_archive"):
                        continue

                    is_rule2 = at_state_top and entry.name in skip_names

                    if entry.is_dir(follow_symlinks=False):
                        try:
                            st = entry.stat(follow_symlinks=False)
                            marks[entry.path] = (st.st_mtime_ns, st.st_size)
                        except OSError:
                            continue

                        if is_rule2:
                            # Record the immediate children of the rule-2
                            # directory, but do not recurse.
                            try:
                                with _REAL_SCANDIR(entry.path) as subit:
                                    for sub in subit:
                                        try:
                                            st = sub.stat(follow_symlinks=False)
                                            marks[sub.path] = (
                                                st.st_mtime_ns,
                                                st.st_size,
                                            )
                                        except OSError:
                                            continue
                            except OSError:
                                # The directory itself is already recorded; an
                                # unlistable one simply shows no children.
                                pass
                        else:
                            stack.append(entry.path)

                    elif entry.is_file(follow_symlinks=False):
                        try:
                            st = entry.stat(follow_symlinks=False)
                            marks[entry.path] = (st.st_mtime_ns, st.st_size)
                        except OSError:
                            continue
        except OSError:
            continue

    return marks


def _changed_dirs(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    """Return the paths whose fingerprint entry changed between two snapshots.

    A path is returned when it was added, removed, or its ``(mtime, size)``
    tuple changed.
    """
    changed = sorted(
        {path for path, _ in set(after.items()) ^ set(before.items())}
    )
    return changed


def _compute_real_data_roots() -> list[str]:
    """Return the real KAINE data roots known at session start, excluding the
    repository and any path that is not a directory.
    """
    candidates: set[str] = set()

    try:
        config = load_kaine_config()
        cfg_root = configured_data_root(config, os.environ)
    except Exception:
        cfg_root = None

    if cfg_root is not None:
        path = str(cfg_root)
        if os.path.isabs(path) and _REAL_ISDIR(path):
            real = os.path.realpath(path)
            if not _is_inside_repo(real):
                candidates.add(real)

    try:
        recommended = storage_step.recommend_root(storage_step.list_filesystems())
    except Exception:
        recommended = None

    if recommended is not None:
        path = str(recommended)
        if _REAL_ISDIR(path):
            real = os.path.realpath(path)
            if not _is_inside_repo(real):
                candidates.add(real)

    return sorted(
        {os.path.realpath(root) for root in candidates if _REAL_ISDIR(root)}
    )


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
    _REAL_DATA_ROOTS: list[str] = []
else:
    _REAL_DATA_ROOTS = _compute_real_data_roots()


@pytest.fixture(scope="session")
def _empty_mounts_path(tmp_path_factory):
    """One empty mounts file shared by the whole test session."""
    path = tmp_path_factory.mktemp("no-mounts") / "mounts"
    path.write_text("")
    return path


@pytest.fixture(autouse=True)
def _no_real_mounts(_empty_mounts_path, monkeypatch, request):
    """Point the storage wizard at the session's empty mounts file so it
    cannot propose a real disk as the data root. Tests of mount parsing opt
    out with @pytest.mark.real_mounts and supply their own file, as today.
    """
    if request.node.get_closest_marker("real_mounts") is None:
        monkeypatch.setattr(
            "kaine.setup.storage_step.MOUNTS_PATH",
            _empty_mounts_path,
        )
    yield


def _format_changed_paths(changed: list[str]) -> str:
    paths = sorted(set(changed))
    displayed = paths[:20]
    if len(paths) > 20:
        displayed.append(f"... and {len(paths) - 20} more")
    return ", ".join(displayed)


@pytest.fixture(autouse=True)
def _repo_state_untouched():
    """Fail any test that writes into the repository's own state/ directory.

    A stray stage file, perception desired-state or consolidation record there
    is read at the next spawn from this checkout: it can mark a fresh being as
    already lived, or hand it a test's developmental stage.
    """
    before = _fingerprint(_REPO_STATE, skip_names=_STATE_SKIP)
    yield
    after = _fingerprint(_REPO_STATE, skip_names=_STATE_SKIP)
    changed = _changed_dirs(before, after)
    if changed:
        pytest.fail(
            "test wrote into the repository's state/ (use tmp_path or monkeypatch "
            f"the default path): {_format_changed_paths(changed)}"
        )


@pytest.fixture(autouse=True)
def _repo_config_untouched():
    """Fail any test that creates or changes a file in the checkout's config/.

    That directory holds the operator's real secrets and overlay; a test that
    writes a token or setting there changes the next real launch.
    """
    before = _fingerprint(_REPO_CONFIG, skip_names=frozenset())
    yield
    after = _fingerprint(_REPO_CONFIG, skip_names=frozenset())
    changed = _changed_dirs(before, after)
    if changed:
        pytest.fail(
            "test wrote into the repository's config/ (pass a tmp_path secrets "
            f"or operator path): {_format_changed_paths(changed)}"
        )


@pytest.fixture(autouse=True)
def _real_data_untouched():
    """Fail any test that writes into a real KAINE data root known at session
    start. Disabled while a kaine.cycle process may be writing to those roots.
    """
    if not _REAL_DATA_ROOTS:
        yield
        return

    kwargs = {
        "skip_names": _STATE_SKIP,
        "full_skip_names": _REAL_ROOT_SKIP,
        "full_skip_prefixes": _REAL_ROOT_SKIP_PREFIXES,
    }
    before = {root: _fingerprint(root, **kwargs) for root in _REAL_DATA_ROOTS}
    yield
    after = {root: _fingerprint(root, **kwargs) for root in _REAL_DATA_ROOTS}

    changed: list[str] = []
    for root in _REAL_DATA_ROOTS:
        changed.extend(_changed_dirs(before[root], after[root]))

    if changed:
        pytest.fail(
            "test wrote into a real KAINE data root (use tmp_path or the "
            f"per-test data root): {_format_changed_paths(changed)}"
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
