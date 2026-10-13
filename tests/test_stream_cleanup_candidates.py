# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The stream cleanup never offers a stream that a producer still writes after the keys rename."""

import importlib.util
import pathlib
import shutil
import subprocess
import sys

from kaine import legacy_names
from kaine.bus.streams import KNOWN_STREAMS
from kaine.evaluation.stream_registry import raw_archive_module_streams
from kaine.legacy_aliases import orphaned_stream_names

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_cleanup_is_empty_while_keys_pending(monkeypatch):
    """Cleanup is empty while the keys scope is pending."""
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")
    assert orphaned_stream_names(KNOWN_STREAMS) == []


def test_cleanup_never_lists_a_live_stream(monkeypatch):
    """Cleanup never lists a stream that a producer still writes."""
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    live = set(KNOWN_STREAMS) | set(raw_archive_module_streams()) | {"cycle.control"}
    result = orphaned_stream_names(live)
    assert not set(result) & live


def test_no_stream_written_after_the_flip_is_a_cleanup_candidate(tmp_path, monkeypatch):
    """No stream written after the keys flip is a cleanup candidate."""
    repo = tmp_path / "repo"
    bus_dir = repo / "kaine" / "bus"
    eval_dir = repo / "kaine" / "evaluation"
    bus_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)

    src_streams = REPO_ROOT / "kaine" / "bus" / "streams.py"
    src_registry = REPO_ROOT / "kaine" / "evaluation" / "stream_registry.py"
    shutil.copy2(src_streams, bus_dir / "streams.py")
    shutil.copy2(src_registry, eval_dir / "stream_registry.py")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )

    codemod_path = REPO_ROOT / "tools" / "maintainer" / "rename_modules.py"
    spec = importlib.util.spec_from_file_location("rename_modules", codemod_path)
    codemod = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = codemod
    spec.loader.exec_module(codemod)

    rc = codemod.main(
        [
            "--apply",
            "--scope",
            "keys",
            "--root",
            str(repo),
            "--table",
            str(REPO_ROOT / "kaine" / "legacy_names.py"),
        ]
    )
    assert rc == 0

    flipped_bus_spec = importlib.util.spec_from_file_location(
        "flipped_bus_streams", str(bus_dir / "streams.py")
    )
    flipped_bus = importlib.util.module_from_spec(flipped_bus_spec)
    monkeypatch.setitem(sys.modules, "kaine.bus.streams", flipped_bus)
    flipped_bus_spec.loader.exec_module(flipped_bus)

    flipped_registry_spec = importlib.util.spec_from_file_location(
        "flipped_stream_registry", str(eval_dir / "stream_registry.py")
    )
    flipped_registry = importlib.util.module_from_spec(flipped_registry_spec)
    monkeypatch.setitem(sys.modules, "kaine.evaluation.stream_registry", flipped_registry)
    flipped_registry_spec.loader.exec_module(flipped_registry)

    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    live_after = (
        set(flipped_bus.KNOWN_STREAMS)
        | set(flipped_registry.raw_archive_module_streams())
        | {"cycle.control"}
    )
    candidates = {
        entry["old"] for entry in legacy_names.STREAM_NAMES if entry["old"] != entry["new"]
    }
    overlap = sorted(live_after & candidates)
    assert overlap == [], f"streams written after the flip are cleanup candidates: {overlap}"
