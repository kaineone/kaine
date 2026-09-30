# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The vendored InternVideo-Next source must import from any working directory.

Study children run with their line directory as the working directory; the
vision encoder must still find ``external.internvideo_next``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from kaine.modules.topos import internvideo_next_loader

REPO = Path(internvideo_next_loader.__file__).resolve().parents[3]


def test_vendored_package_resolves_from_a_foreign_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def _is_repo(entry: str) -> bool:
        return Path(entry or ".").resolve() == REPO

    monkeypatch.setattr(sys, "path", [p for p in sys.path if not _is_repo(p)])
    for name in list(sys.modules):
        if name == "external" or name.startswith("external."):
            monkeypatch.delitem(sys.modules, name)

    # Precondition: without the helper the vendored package is not importable here.
    assert importlib.util.find_spec("external") is None

    internvideo_next_loader._ensure_repo_root_importable()

    spec = importlib.util.find_spec("external.internvideo_next")
    assert spec is not None
    assert Path(spec.submodule_search_locations[0]) == REPO / "external" / "internvideo_next"
