# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Opt-in regression test for preserved local state under legacy name mappings.

This module runs only when ``KAINE_LOCAL_DATA_ROOT`` points at a checkout that
contains ``backups/`` and ``state/forks/``. It copies those trees once into a
temporary directory, points every reader at the copy, and asserts that no old
module names leak through the read-map functions.
"""

import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.lifecycle import preservation, rename_state, stage
from kaine.lifecycle.snapshot import ForkSnapshot, load_snapshot
from kaine.security import crypto
from kaine.security.crypto import CryptoConfig, StateEncryptor

_ROOT_ENV = os.environ.get("KAINE_LOCAL_DATA_ROOT", "").strip()

if not _ROOT_ENV:
    pytest.skip(
        "KAINE_LOCAL_DATA_ROOT not set; skipping local-data tests",
        allow_module_level=True,
    )

ROOT = Path(_ROOT_ENV)

if not (ROOT / "backups").is_dir() or not (ROOT / "state" / "forks").is_dir():
    pytest.skip(
        "KAINE_LOCAL_DATA_ROOT missing backups/ and state/forks/; skipping local-data tests",
        allow_module_level=True,
    )

_BACKUPS = ROOT / "backups"
_FORKS = ROOT / "state" / "forks"

BUNDLE_NAMES = sorted(p.name for p in _BACKUPS.iterdir() if p.is_dir())
FORK_NAMES = sorted(
    p.name for p in _FORKS.iterdir() if p.is_dir() and (p / "snapshot.json").is_file()
)

PRESERVATION_NAMES = [n for n in BUNDLE_NAMES if n.startswith("preservation_")]
DECOMMISSION_NAMES = [n for n in BUNDLE_NAMES if not n.startswith("preservation_")]


def _tree_listing(path: Path) -> dict[str, tuple[int, int]]:
    listing: dict[str, tuple[int, int]] = {}
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        base = Path(dirpath)
        for filename in filenames:
            full = base / filename
            try:
                stat = full.lstat()
            except OSError:
                continue
            rel = full.relative_to(path).as_posix()
            listing[rel] = (stat.st_size, stat.st_mtime_ns)
    return listing


def _old_keys() -> set[str]:
    return {k for k, v in legacy_names.MODULES.items() if v["new_key"] != k}


def _old_record_fields() -> set[str]:
    return {entry["old"] for entry in legacy_names.RECORD_FIELDS}


def _old_stage_fields() -> set[str]:
    return {entry["old"] for entry in legacy_names.STAGE_FIELDS}


@pytest.fixture(scope="module")
def local_data_copy():
    with tempfile.TemporaryDirectory(prefix="kaine-local-data-") as tmp:
        copy_root = Path(tmp) / "root"
        backups_copy = copy_root / "backups"
        forks_copy = copy_root / "state" / "forks"

        pre_backup_listing = _tree_listing(_BACKUPS)
        pre_forks_listing = _tree_listing(_FORKS)

        shutil.copytree(_BACKUPS, backups_copy, symlinks=True)
        shutil.copytree(_FORKS, forks_copy, symlinks=True)

        try:
            yield copy_root
        finally:
            post_backup_listing = _tree_listing(_BACKUPS)
            post_forks_listing = _tree_listing(_FORKS)
            assert post_backup_listing == pre_backup_listing, (
                "real backups tree was modified during the test"
            )
            assert post_forks_listing == pre_forks_listing, (
                "real forks tree was modified during the test"
            )


@pytest.fixture(autouse=True)
def _enable_read_maps(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")
    monkeypatch.setattr(stage, "STAGES", ("development", "embodied"))
    monkeypatch.setattr(
        crypto,
        "_active",
        StateEncryptor(CryptoConfig(enabled=False)),
    )


def test_at_least_one_bundle_and_fork(local_data_copy):
    bundle_dirs = [d for d in (local_data_copy / "backups").iterdir() if d.is_dir()]
    fork_dirs = [
        d
        for d in (local_data_copy / "state" / "forks").iterdir()
        if d.is_dir() and (d / "snapshot.json").is_file()
    ]
    print(f"Discovered {len(bundle_dirs)} bundles and {len(fork_dirs)} fork trees")
    assert len(bundle_dirs) >= 1
    assert len(fork_dirs) >= 1


@pytest.mark.parametrize("name", PRESERVATION_NAMES, ids=PRESERVATION_NAMES)
def test_preservation_bundle(name, local_data_copy):
    bundle = local_data_copy / "backups" / name
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}

    if "modules" in manifest:
        mapped = legacy_aliases.map_module_list(manifest["modules"])
        assert len(mapped) == len(manifest["modules"])
        assert not any(m in _old_keys() for m in mapped)

    # Encrypted bundles cannot be read further without the state key.
    if (bundle / "bundle.tar.enc").is_file() and not os.environ.get("KAINE_STATE_KEY"):
        return

    tar_path = bundle / "bundle.tar"
    if tar_path.is_file():
        members = preservation._read_bundle_members(bundle)
        assert "snapshot.json" in members
        assert not any(k.startswith(("phantasia/", "gestation/")) for k in members)

        snapshot = ForkSnapshot.from_dict(json.loads(members["snapshot.json"]))
        assert snapshot.modules
        assert not any(m in _old_keys() for m in snapshot.modules)

        with tarfile.open(tar_path, "r") as tf:
            for member in tf.getmembers():
                mapped_name = legacy_aliases.map_bundle_member(member.name)
                assert not mapped_name.startswith("gestation/")
                first_segment = mapped_name.split("/")[0]
                assert first_segment not in _old_keys()

    stage_record = preservation.read_bundle_stage(bundle)
    if isinstance(stage_record, dict):
        mapped = legacy_aliases.map_stage_record(stage_record)
        assert not any(k in _old_stage_fields() for k in mapped)
        if "stage" in mapped:
            coerced = stage._coerce_stage(mapped["stage"])
            assert coerced in {"development", "embodied"}


@pytest.mark.parametrize("name", DECOMMISSION_NAMES, ids=DECOMMISSION_NAMES)
def test_decommission_backup(name, local_data_copy):
    bundle = local_data_copy / "backups" / name
    snapshot_path = bundle / "snapshot.json"

    if snapshot_path.is_file():
        snapshot = ForkSnapshot.from_dict(json.loads(snapshot_path.read_text()))
        assert not any(m in _old_keys() for m in snapshot.modules)

    intent_path = bundle / "intent_expression.jsonl"
    if intent_path.is_file():
        bad_lines = 0
        for line in intent_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue

            if not isinstance(record, dict):
                bad_lines += 1
                continue

            mapped = legacy_aliases.map_record(record)
            assert not any(k in _old_record_fields() for k in mapped)

            source = mapped.get("source")
            if isinstance(source, str):
                assert source not in _old_keys()

        assert bad_lines == 0


@pytest.mark.parametrize("name", FORK_NAMES, ids=FORK_NAMES)
def test_fork_tree(name, local_data_copy, monkeypatch):
    tree = local_data_copy / "state" / "forks" / name
    data = (tree / "snapshot.json").read_bytes()

    if data.lstrip()[:1] != b"{":
        if not os.environ.get("KAINE_STATE_KEY"):
            pytest.skip(f"{name}: snapshot is encrypted; set KAINE_STATE_KEY to check it")
        monkeypatch.setattr(
            crypto,
            "_active",
            StateEncryptor(CryptoConfig.from_section({"enabled": True})),
        )

    snapshot = load_snapshot(tree.parent, name)
    raw = json.loads(crypto.get_state_encryptor().maybe_decrypt(data).decode("utf-8"))

    assert not any(m in _old_keys() for m in snapshot.modules)
    assert len(snapshot.modules) == len(raw.get("modules", {}))

    plan = rename_state.plan(tree)
    assert isinstance(plan, list)
