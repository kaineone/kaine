# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fail-closed stage value handling."""

from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path

import pytest

from kaine import legacy_names
from kaine.cycle import __main__ as cycle_main
from kaine.cycle import revive_boot
from kaine.cycle.revive_boot import ReviveRefused, prepare_revive
from kaine.lifecycle import preservation, stage
from kaine.security import crypto
from kaine.security.crypto import CryptoConfig, StateEncryptor

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


def _hermetic_cwd(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize(
    "value",
    [
        "embod1ed",
        "embodied\x00",
        "adolescence",
        "development",
        42,
        3.5,
        None,
        True,
        ["embodied"],
        {"stage": "embodied"},
    ],
)
def test_read_stage_refuses_unrecognized_value(tmp_path: Path, value) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"stage": value}).encode("utf-8")
    p.write_bytes(content)
    before = p.read_bytes()
    with pytest.raises(stage.StageValueError) as excinfo:
        stage.read_stage(p)
    assert str(p) in str(excinfo.value)
    assert repr(value) in str(excinfo.value)
    assert p.read_bytes() == before


def test_read_stage_refuses_long_value(tmp_path: Path) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    value = "x" * 500
    content = json.dumps({"stage": value}).encode("utf-8")
    p.write_bytes(content)
    before = p.read_bytes()
    with pytest.raises(stage.StageValueError) as excinfo:
        stage.read_stage(p)
    exc = excinfo.value
    assert len(exc.value_repr) == 64
    assert exc.value_repr.endswith("...")
    assert exc.value_repr in str(exc)
    assert p.read_bytes() == before


def test_read_stage_missing_key_defaults_to_development(tmp_path: Path) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({"lived_seconds": 1.0}).encode("utf-8")
    p.write_bytes(content)
    before = p.read_bytes()
    result = stage.read_stage(p)
    assert result is not None
    assert result.stage == stage.DEVELOPMENT
    assert p.read_bytes() == before


def test_read_stage_unparseable_file_fails_safe_to_embodied(tmp_path: Path) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    content = b"{not json"
    p.write_bytes(content)
    before = p.read_bytes()
    result = stage.read_stage(p)
    assert result is not None
    assert result.stage == stage.EMBODIED
    assert p.read_bytes() == before


@pytest.mark.parametrize("value", ["embod1ed", "adolescence", 7])
def test_cycle_refuses_to_boot_on_bad_stage(tmp_path: Path, monkeypatch, capsys, value) -> None:
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")
    stage_path = tmp_path / "lifecycle" / "stage.json"
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)
    content = json.dumps({"stage": value}).encode("utf-8")
    stage_path.write_bytes(content)
    before = stage_path.read_bytes()
    calls: list = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)
    rc = cycle_main.main([])
    assert rc == cycle_main.STAGE_REFUSED_EXIT
    assert calls == []
    captured = capsys.readouterr()
    assert "stage refused" in captured.err
    assert str(stage_path) in captured.err
    assert repr(value) in captured.err
    assert stage_path.read_bytes() == before


def test_cycle_boots_on_valid_embodied_stage(tmp_path: Path, monkeypatch, capsys) -> None:
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")
    stage_path = tmp_path / "lifecycle" / "stage.json"
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)
    content = json.dumps({"stage": "embodied"}).encode("utf-8")
    stage_path.write_bytes(content)
    before = stage_path.read_bytes()
    calls: list = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)
    rc = cycle_main.main([])
    assert rc == 0
    assert len(calls) == 1
    assert stage_path.read_bytes() == before


def test_revive_refuses_unrecognized_bundle_stage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(revive_boot, "read_bundle_stage", lambda _b: {"stage": "adolescence"})
    monkeypatch.setattr(
        revive_boot._preservation,
        "_read_bundle_members",
        lambda _b: {"snapshot.json": "{}"},
    )
    with pytest.raises(ReviveRefused) as excinfo:
        prepare_revive(tmp_path)
    assert "adolescence" in str(excinfo.value)
    assert "stage.json" in str(excinfo.value)


def test_never_regress_with_synthetic_alias(monkeypatch) -> None:
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")
    monkeypatch.setattr(stage, "STAGES", ("development", "embodied"))
    assert stage._coerce_stage("development") == "development"
    assert stage._coerce_stage("development") == "development"
    assert stage.StageState.from_dict({"stage": "development"}).stage == "development"
    with pytest.raises(stage.StageValueError):
        stage._coerce_stage("larval")


def test_pending_scope_keeps_development_readable() -> None:
    assert legacy_names.SCOPE_STATUS.get("persisted") != "done"
    assert stage._coerce_stage("development") == "development"


def test_stage_alias_and_constants_move_together() -> None:
    """Each stage-value alias is live only when the code reads its new value."""
    for entry in legacy_names.STAGE_VALUES:
        if legacy_names.SCOPE_STATUS.get(entry["scope"]) == "done":
            assert entry["new"] in stage.STAGES
            assert entry["old"] not in stage.STAGES
        else:
            assert entry["old"] in stage.STAGES


@pytest.mark.parametrize("text", ["null", "[]", "0", '""', "false"])
def test_read_stage_refuses_non_object_top_level(tmp_path: Path, text) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    before = p.read_bytes()
    with pytest.raises(stage.StageValueError) as excinfo:
        stage.read_stage(p)
    assert str(p) in str(excinfo.value)
    assert "not hold a JSON object" in str(excinfo.value)
    assert p.read_bytes() == before


@pytest.mark.parametrize("text", ["null", "[]", "0", '""', "false"])
def test_cycle_refuses_to_boot_on_non_object_stage(
    tmp_path: Path, monkeypatch, capsys, text
) -> None:
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")
    stage_path = tmp_path / "lifecycle" / "stage.json"
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)
    stage_path.write_text(text)
    before = stage_path.read_bytes()
    calls: list = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)
    rc = cycle_main.main([])
    assert rc == cycle_main.STAGE_REFUSED_EXIT
    assert calls == []
    captured = capsys.readouterr()
    assert "stage refused" in captured.err
    assert str(stage_path) in captured.err
    assert stage_path.read_bytes() == before


def test_empty_object_stage_reads_as_developmental_stage(tmp_path: Path) -> None:
    p = tmp_path / "lifecycle" / "stage.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    before = p.read_bytes()
    result = stage.read_stage(p)
    assert result is not None
    assert result.stage == stage.DEVELOPMENT
    assert p.read_bytes() == before


def test_revive_refuses_non_object_bundle_stage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(revive_boot, "read_bundle_stage", lambda _b: [])
    monkeypatch.setattr(
        revive_boot._preservation,
        "_read_bundle_members",
        lambda _b: {"snapshot.json": "{}"},
    )
    with pytest.raises(ReviveRefused) as excinfo:
        prepare_revive(tmp_path)
    assert "stage.json" in str(excinfo.value)


def test_read_bundle_stage_refuses_null(tmp_path: Path, monkeypatch) -> None:
    bundle_dir = tmp_path / "b"
    bundle_dir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "snapshot.json").write_bytes(b"{}")
    (work / "stage.json").write_bytes(b"null")
    tar_path = bundle_dir / "bundle.tar"
    with tarfile.open(tar_path, "w") as tar:
        tar.add(work / "snapshot.json", arcname="snapshot.json")
        tar.add(work / "stage.json", arcname="stage.json")
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    with pytest.raises(preservation.ReviveError):
        preservation.read_bundle_stage(bundle_dir)
