# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for rename_state migration wired into the boot path."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from kaine import legacy_names
from kaine.cycle import __main__ as cycle_main
from kaine.lifecycle import decommission, rename_state

OLD_SLEEP = next(k for k, e in legacy_names.MODULES.items() if e["new_key"] == "sleep")

OLD_MATURATION_REQUEST = next(
    e["old"] for e in legacy_names.STATE_PATHS
    if e["new"] == "lifecycle/maturation_request.json"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


def _hermetic_cwd(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    monkeypatch.chdir(tmp_path)


def test_migrate_at_boot_moves_an_old_tree_and_is_then_a_noop(tmp_path):
    state_root = tmp_path / "state"
    old_dir = state_root / OLD_SLEEP
    old_dir.mkdir(parents=True)
    (old_dir / "organ_window.json").write_bytes(b"{}")

    old_maturity = state_root / OLD_MATURATION_REQUEST
    old_maturity.parent.mkdir(parents=True, exist_ok=True)
    request_bytes = b'{"request_id": "r"}'
    old_maturity.write_bytes(request_bytes)

    result = rename_state.migrate_at_boot({}, state_root)
    assert result.status != "noop"

    assert (state_root / "sleep" / "organ_window.json").read_bytes() == b"{}"
    assert (state_root / "lifecycle" / "maturation_request.json").read_bytes() == request_bytes
    assert not old_dir.exists()
    assert not old_maturity.exists()

    second = rename_state.migrate_at_boot({}, state_root)
    assert second.status == "noop"


def test_migrate_at_boot_refuses_old_and_new_together(tmp_path):
    state_root = tmp_path / "state"
    old_dir = state_root / OLD_SLEEP
    old_dir.mkdir(parents=True)
    (old_dir / "organ_window.json").write_bytes(b"old")

    new_dir = state_root / "sleep"
    new_dir.mkdir(parents=True)
    (new_dir / "organ_window.json").write_bytes(b"new")

    before = {p.relative_to(state_root): p.read_bytes() for p in state_root.rglob("*") if p.is_file()}

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate_at_boot({}, state_root)

    after = {p.relative_to(state_root): p.read_bytes() for p in state_root.rglob("*") if p.is_file()}
    assert after == before


def test_migrate_at_boot_without_state_root_is_a_noop(tmp_path):
    state_root = tmp_path / "missing"
    result = rename_state.migrate_at_boot({}, state_root)
    assert result == rename_state.RenameResult("noop", ())


def test_migrate_at_boot_builds_a_qdrant_client_when_in_use(tmp_path, monkeypatch):
    close_calls = []

    class FakeClient:
        def get_collections(self):
            return SimpleNamespace(collections=[])

        def get_aliases(self):
            return SimpleNamespace(aliases=[])

        def close(self):
            close_calls.append(True)

    monkeypatch.setattr(decommission, "qdrant_in_use", lambda config: True)
    monkeypatch.setattr(decommission, "_qdrant_client", lambda config: FakeClient())

    state_root = tmp_path / "state"
    state_root.mkdir()

    result = rename_state.migrate_at_boot({}, state_root)
    assert result.status == "noop"
    assert close_calls == [True]


def test_cycle_main_refuses_a_conflicting_tree(tmp_path, monkeypatch, capsys):
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")

    state_dir = tmp_path / "state"
    (state_dir / OLD_SLEEP).mkdir(parents=True)
    (state_dir / OLD_SLEEP / "organ_window.json").write_text("old")
    (state_dir / "sleep").mkdir(parents=True)
    (state_dir / "sleep" / "other.json").write_text("new")

    calls = []

    async def fake_boot(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", fake_boot)

    ret = cycle_main.main([])
    assert ret == cycle_main.RENAME_REFUSED_EXIT

    captured = capsys.readouterr()
    assert "state rename refused" in captured.err
    assert not calls
    assert (state_dir / OLD_SLEEP).exists()
    assert (state_dir / "sleep").exists()


def test_migrate_at_boot_reports_an_unreachable_qdrant_as_a_refusal(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    state_root.mkdir()

    class _Unreachable:
        def get_collections(self):
            raise RuntimeError("qdrant refused the key")

        def get_aliases(self):
            raise RuntimeError("qdrant refused the key")

        def close(self):
            pass

    monkeypatch.setattr(decommission, "qdrant_in_use", lambda _cfg: True)
    monkeypatch.setattr(decommission, "_qdrant_client", lambda _cfg: _Unreachable())
    with pytest.raises(rename_state.RenameStateError, match="Qdrant could not be used"):
        rename_state.migrate_at_boot({}, state_root)
