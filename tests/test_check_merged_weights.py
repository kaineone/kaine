# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The read-only check for snapshots holding concatenated weight groups."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from kaine.bus.client import AsyncBus
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot
from kaine.lifecycle.strategies import UnionMergeStrategy
from kaine.modules.audition.forward import AuditoryForwardModel
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.interoception.module import Interoception
from kaine.modules.vision.forward import LatentForwardModel

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_merged_weights", REPO / "tools" / "maintainer" / "check_merged_weights.py"
)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


class _Reader:
    def read(self) -> dict[str, Any]:
        return {}

    @property
    def cycle_latency_window(self) -> int:
        return 4


def _vision_state(seed: int) -> dict[str, Any]:
    model = LatentForwardModel(latent_dim=4, units=3, seed=seed, context_dim=CONTEXT_DIM)
    return {"encoder_model_id": "test/encoder", "forward_model": model.state_dict()}


def _interoception_state(seed: int) -> dict[str, Any]:
    module = Interoception(
        MagicMock(spec=AsyncBus), reader=_Reader(), reservoir_seed=seed, forward_model_units=4
    )
    return module.serialize()


def _write(root: Path, modules: dict[str, Any], **meta: Any) -> str:
    snap = ForkSnapshot(modules=modules, metadata=dict(meta))
    save_snapshot(root, snap)
    return snap.id


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "forks"
    path.mkdir()
    return path


def _garbled_root(root: Path) -> tuple[str, str]:
    union = UnionMergeStrategy()
    clean = _write(root, {"vision": _vision_state(1), "interoception": _interoception_state(11)})
    garbled = _write(
        root,
        {
            "vision": union.merge(_vision_state(1), _vision_state(2)),
            "interoception": union.merge(_interoception_state(11), _interoception_state(22)),
        },
        merged_from=["aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"],
    )
    return clean, garbled


def test_forward_model_layer_count_matches_the_real_networks():
    import torch.nn as nn

    for model in (
        LatentForwardModel(latent_dim=4, units=3, context_dim=CONTEXT_DIM),
        AuditoryForwardModel(feature_dim=4, units=3, context_dim=CONTEXT_DIM),
    ):
        linears = [m for m in model._net if isinstance(m, nn.Linear)]
        assert len(linears) == check.FORWARD_MODEL_LAYERS


def test_lists_only_the_concatenated_snapshot(root: Path):
    clean, garbled = _garbled_root(root)
    found, unreadable = check.find_concatenated(root)
    assert not unreadable
    assert {item["snapshot"] for item in found} == {garbled}
    modules = {(item["module"], item["key"]) for item in found}
    assert ("vision", "forward_model") in modules
    assert ("interoception", "forward_model") in modules
    reasons = " ".join(item["reason"] for item in found)
    assert "4 layers for a 2-layer network" in reasons
    assert "16 weight rows for a 8-feature model" in reasons


def test_a_merge_made_after_the_fix_is_not_listed(root: Path):
    mgr = ForkManager(root)

    class _Captured:
        def __init__(self, name: str, state: dict[str, Any]) -> None:
            self.name, self._state = name, state

        def serialize(self) -> dict[str, Any]:
            return self._state

    class _Registry:
        def __init__(self, modules: list[Any]) -> None:
            self._modules = modules

        def all_modules(self):
            return iter(self._modules)

    a = mgr.snapshot(_Registry([_Captured("vision", _vision_state(1))])).id
    b = mgr.snapshot(_Registry([_Captured("vision", _vision_state(2))])).id
    mgr.merge(a, b, module_weights_from="b")
    found, unreadable = check.find_concatenated(root)
    assert found == [] and unreadable == []


def _tree(root: Path) -> dict[str, tuple[int, int, str]]:
    out: dict[str, tuple[int, int, str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            digest = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if stat.S_ISREG(st.st_mode)
                else ""
            )
            out[str(path.relative_to(root))] = (st.st_mode, st.st_mtime_ns, digest)
    return out


def test_opens_snapshots_read_only_and_writes_nothing(root: Path, monkeypatch, capsys):
    clean, garbled = _garbled_root(root)
    before = _tree(root)

    opened: list[tuple[str, str]] = []
    real_open = io.open

    def guarded_open(file, mode="r", *args, **kwargs):
        path = Path(os.fspath(file)) if isinstance(file, (str, os.PathLike)) else None
        if path is not None and str(path.resolve()).startswith(str(root.resolve())):
            opened.append((str(path), mode))
            assert set(mode) <= {"r", "b", "t"}, f"{path} opened with mode {mode!r}"
        return real_open(file, mode, *args, **kwargs)

    def no_write(*args, **kwargs):
        raise AssertionError("the check must not write, move or delete")

    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(builtins, "open", guarded_open)
    for name in ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs"):
        monkeypatch.setattr(os, name, no_write)
    monkeypatch.setattr(
        check, "_load_config", lambda: {"security": {"state_encryption": {"enabled": False}}}
    )

    status = check.main(["--fork-root", str(root)])

    assert status == 1
    out = capsys.readouterr().out
    assert garbled in out and clean not in out
    assert "merged from aaaaaaaaaaaaaaaa + bbbbbbbbbbbbbbbb" in out
    assert opened, "the check read no snapshot"
    assert _tree(root) == before


def test_clean_root_exits_zero(root: Path, monkeypatch, capsys):
    _write(root, {"vision": _vision_state(1)})
    monkeypatch.setattr(
        check, "_load_config", lambda: {"security": {"state_encryption": {"enabled": False}}}
    )
    assert check.main(["--fork-root", str(root)]) == 0
    assert "no snapshot" in capsys.readouterr().out


def test_encryption_failure_stops_before_reading(root: Path, monkeypatch, capsys):
    _write(root, {"vision": _vision_state(1)})

    def broken() -> dict[str, Any]:
        raise RuntimeError("no key")

    monkeypatch.setattr(check, "_load_config", broken)
    assert check.main(["--fork-root", str(root)]) == 2
    assert "state encryption could not be installed" in capsys.readouterr().err
