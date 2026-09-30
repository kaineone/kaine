# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.storage import data_root, install_data_root, resolve, set_data_root


@pytest.fixture(autouse=True)
def _reset_process_root(monkeypatch):
    set_data_root(None)
    monkeypatch.delenv("KAINE_DATA_ROOT", raising=False)
    yield
    set_data_root(None)


def test_resolve_without_root_relative_unchanged():
    assert resolve("state/cycle/runtime.json") == Path("state/cycle/runtime.json")


def test_resolve_without_root_absolute_unchanged():
    absolute = Path("/tmp/state/cycle/runtime.json")
    assert resolve(absolute) == absolute


def test_resolve_with_root_relative_under_root(tmp_path: Path):
    root = tmp_path / "root"
    set_data_root(root)
    assert resolve("state/cycle/runtime.json") == root / "state/cycle/runtime.json"


def test_resolve_with_root_absolute_unchanged(tmp_path: Path):
    root = tmp_path / "root"
    set_data_root(root)
    absolute = Path("/tmp/state/cycle/runtime.json")
    assert resolve(absolute) == absolute


def test_install_data_root_from_config(tmp_path: Path):
    config = {"storage": {"data_root": str(tmp_path)}}
    root = install_data_root(config)
    assert root == tmp_path.resolve()
    assert data_root() == tmp_path.resolve()


def test_install_data_root_from_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KAINE_DATA_ROOT", str(tmp_path))
    root = install_data_root({})
    assert root == tmp_path.resolve()
    assert data_root() == tmp_path.resolve()


def test_install_data_root_no_config_returns_none():
    root = install_data_root({})
    assert root is None
    assert data_root() is None


def test_async_jsonl_sink_follows_root(tmp_path: Path):
    root = tmp_path / "root"
    set_data_root(root)
    sink = AsyncJsonlSink("state/x", name="t")
    assert sink._dir == root / "state/x"


def test_async_jsonl_sink_no_root_relative(tmp_path: Path):
    set_data_root(None)
    sink = AsyncJsonlSink("state/x", name="t")
    assert sink._dir == Path("state/x")


def test_cycle_control_installs_root(monkeypatch, tmp_path: Path):
    from kaine.cycle import control

    root = tmp_path / "data"
    monkeypatch.setattr(
        control,
        "load_kaine_config",
        lambda: {"storage": {"data_root": str(root)}},
    )

    captured: dict[str, object] = {}

    def fake_run_preserve(
        reason: str,
        stop: bool,
        wait: float,
        *,
        request_path: Path | None = None,
        result_path: Path | None = None,
        sleep=None,
        clock=None,
    ) -> int:
        captured["request_path"] = request_path
        captured["result_path"] = result_path
        return 0

    monkeypatch.setattr(control, "run_preserve", fake_run_preserve)

    assert control.main(["preserve", "--reason", "test"]) == 0
    assert data_root() == root.resolve()

    from kaine.cycle.preserve_watch import REQUEST_PATH, RESULT_PATH

    assert captured["request_path"] == resolve(REQUEST_PATH)
    assert captured["result_path"] == resolve(RESULT_PATH)
