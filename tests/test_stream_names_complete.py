# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Every stream name the keys rename moves is listed in STREAM_NAMES, derived from the registries and the codemod itself."""

import ast
import importlib.util
import pathlib
import subprocess
import sys

from kaine import legacy_names
from kaine.bus.streams import KNOWN_STREAMS, PERCEPTION_FEED_STREAM
from kaine.evaluation.stream_registry import raw_archive_module_streams

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_stream_names_complete(tmp_path):
    names = sorted(
        set(KNOWN_STREAMS)
        | set(raw_archive_module_streams())
        | {"cycle.control"}
    )

    probe_dir = tmp_path / "repo" / "kaine"
    probe_dir.mkdir(parents=True)
    probe_path = probe_dir / "stream_probe.py"
    probe_path.write_text(
        "NAMES = [\n"
        + "".join(f'    "{name}",\n' for name in names)
        + "]\n",
        encoding="utf-8",
    )

    repo = tmp_path / "repo"
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

    source = probe_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assign = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "NAMES" for target in node.targets)
    )
    new_names = ast.literal_eval(ast.get_source_segment(source, assign.value))

    missing = []
    for old, new in zip(names, new_names):
        if old != new:
            entry = {"old": old, "new": new, "scope": "keys"}
            if entry not in legacy_names.STREAM_NAMES:
                missing.append(entry)

    assert missing == [], f"Missing STREAM_NAMES entries: {missing}"


def test_perception_feed_stream_listed_once():
    """The perception feed's stream appears exactly once among the produced streams."""
    streams = raw_archive_module_streams()
    assert streams.count(PERCEPTION_FEED_STREAM) == 1
