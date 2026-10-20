
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Prove that neither housekeeping path touches the protected classes.

Paper 3.5: "Neither touches the memory stores, world model, self-model
and identity, voice adapters, or preservations." These tests plant real
files for every protected class and make them as tempting as possible:
they are listed as process-log backups, identical copies exist in the
archive so a "verified export" check could match, the disk budget is a
single byte, and the awake floor sees a completely full disk. Both the
sleep pass (``Housekeeper.run``) and the awake floor
(``AwakeFloor.check_once`` via ``Housekeeper.reclaim_regenerable``) are
then run, and every protected file must keep its SHA-256 and mtime.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import kaine.storage
from kaine.cycle.housekeeping_floor import AwakeFloor
from kaine.housekeeping_pressure import HousekeepingPressure
from kaine.modules.sleep.housekeeping import (
    Housekeeper,
    HousekeepingConfig,
    HousekeepingRefused,
)
from kaine.persistence.study_record_gate import StudyRecordGate

TODAY = "2026-10-20"
STUDY_DATE = "2026-10-01"

PROTECTED_FILES: tuple[str, ...] = (
    "state/episodic_memory/store.db",
    "state/episodic_memory/qdrant/collection.bin",
    "state/world_model/model.pt",
    "state/self_model/self_model.json",
    "state/identity/entity.json",
    "state/sleep/adapters/adapter.safetensors",
    "state/preservation/bundle.tar",
    "state/forks/snapshot.json",
    # A daily-named file inside the protected root: the name alone must
    # never make a file under state/ reclaimable.
    "state/research/raw_bus_archive/raw-2026-10-01.jsonl",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class ProtectedEnv:
    """Everything a test needs: files, fingerprints, and the housekeeper."""

    root: Path
    archive: Path
    protected: dict[str, Path]
    fingerprints: dict[Path, tuple[str, float]]
    symlink: Path
    study_file: Path
    study_sha256: str
    housekeeper: Housekeeper


def _build_env(root: Path) -> ProtectedEnv:
    protected: dict[str, Path] = {}
    contents: dict[str, bytes] = {}
    for rel in PROTECTED_FILES:
        content = (f"protected payload for {rel}\n").encode("utf-8") * 4
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        protected[rel] = path
        contents[rel] = content

    # A symlink inside an allowed root, with a tempting daily-style name,
    # pointing at the episodic store.
    symlink = root / "data" / "evaluation" / "store-2020-01-01.jsonl"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(protected["state/episodic_memory/store.db"], symlink)

    # Identical copies of every protected file in the archive, both under
    # a root-shaped name and under the state/ tree, so a "verified export"
    # check could match if the code ever looked there for a protected file.
    archive = root / "archive"
    for rel, content in contents.items():
        dest_eval = archive / "evaluation" / Path(rel).name
        dest_eval.parent.mkdir(parents=True, exist_ok=True)
        dest_eval.write_bytes(content)
        dest_state = archive / rel
        dest_state.parent.mkdir(parents=True, exist_ok=True)
        dest_state.write_bytes(content)

    # The one legitimate closed daily study-record file.
    study_file = (
        root
        / "data"
        / "evaluation"
        / "research_events"
        / f"research_events-{STUDY_DATE}.jsonl"
    )
    study_file.parent.mkdir(parents=True, exist_ok=True)
    study_file.write_bytes(b'{"study": "closed"}\n' * 3)

    fingerprints = {
        path: (_sha256(path), path.stat().st_mtime) for path in protected.values()
    }

    config = HousekeepingConfig(
        disk_budget_bytes=1,
        memory_budget_bytes=10**18,
        time_allowance_s=3600.0,
        archive_dir=str(archive),
    )
    tempting = [*protected.values(), symlink]
    housekeeper = Housekeeper(
        config,
        log_backups=lambda: list(tempting),
        today=lambda: TODAY,
    )

    return ProtectedEnv(
        root=root,
        archive=archive,
        protected=protected,
        fingerprints=fingerprints,
        symlink=symlink,
        study_file=study_file,
        study_sha256=_sha256(study_file),
        housekeeper=housekeeper,
    )


@pytest.fixture(autouse=True)
def protected_env(tmp_path):
    previous_root = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    try:
        yield _build_env(tmp_path)
    finally:
        kaine.storage.set_data_root(previous_root)


def _assert_protected_untouched(env: ProtectedEnv) -> None:
    for rel, path in env.protected.items():
        assert path.is_file(), f"protected file is missing: {rel}"
        assert not path.is_symlink(), f"protected file became a symlink: {rel}"
        expected_sha, expected_mtime = env.fingerprints[path]
        assert _sha256(path) == expected_sha, f"protected content changed: {rel}"
        assert path.stat().st_mtime == expected_mtime, (
            f"protected mtime changed: {rel}"
        )
    assert os.path.islink(env.symlink), "the symlink was removed or replaced"
    assert os.readlink(env.symlink) == str(
        env.protected["state/episodic_memory/store.db"]
    ), "the symlink was retargeted"


@pytest.mark.asyncio
async def test_sleep_pass_leaves_protected_files_untouched(protected_env):
    try:
        await protected_env.housekeeper.run()
    except HousekeepingRefused:
        pass  # a refusal is safe; it must never touch protected files either

    _assert_protected_untouched(protected_env)

    # The legitimate closed study file is the only thing that moved: it was
    # exported to the archive under its checksum and removed locally.
    assert not protected_env.study_file.exists()
    exported = (
        protected_env.archive
        / "evaluation"
        / "research_events"
        / protected_env.study_file.name
    )
    assert exported.is_file()
    assert _sha256(exported) == protected_env.study_sha256


@pytest.mark.asyncio
async def test_reclaim_regenerable_leaves_protected_files_untouched(protected_env):
    try:
        await protected_env.housekeeper.reclaim_regenerable(
            free_bytes=lambda: 0, target_free=10**18
        )
    except HousekeepingRefused:
        pass  # acceptable, but nothing protected may change before it

    _assert_protected_untouched(protected_env)

    # Reclaim never exports, so the unexported study file must survive too.
    assert protected_env.study_file.is_file()
    assert _sha256(protected_env.study_file) == protected_env.study_sha256


@pytest.mark.asyncio
async def test_awake_floor_leaves_protected_files_untouched(protected_env):
    gate = StudyRecordGate()

    def fake_disk_usage(path):
        # A completely full disk that no reclaim can ever satisfy.
        return SimpleNamespace(total=10**19, used=0, free=0)

    floor = AwakeFloor(
        protected_env.housekeeper,
        HousekeepingPressure(),
        volumes={
            "data": protected_env.root / "data",
            "state": protected_env.root / "state",
        },
        reserve_bytes=10**18,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=fake_disk_usage,
    )
    # A refusal is acceptable here; what matters is that nothing protected changes.
    with contextlib.suppress(HousekeepingRefused):
        await floor.check_once()

    _assert_protected_untouched(protected_env)

    # Reclaiming could not satisfy the reserve, so the floor fell back to
    # suspending the study record.
    assert gate.suspended


@pytest.mark.parametrize("rel", list(PROTECTED_FILES) + ["<symlink>"])
def test_check_allowed_refuses_every_protected_path(protected_env, rel):
    path = (
        protected_env.symlink if rel == "<symlink>" else protected_env.protected[rel]
    )
    with pytest.raises(HousekeepingRefused):
        protected_env.housekeeper.check_allowed(path)


def test_no_public_deletion_bypass_exists():
    public = sorted(n for n in dir(Housekeeper) if not n.startswith("_"))
    assert public == sorted(
        [
            "check_allowed",
            "disk_bytes",
            "disk_excess",
            "candidates",
            "run",
            "reclaim_regenerable",
        ]
    ), (
        "Housekeeper gained a public method; a new deletion path has to be "
        "added deliberately and this test updated"
    )
