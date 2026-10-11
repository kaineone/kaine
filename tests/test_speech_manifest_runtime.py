# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Runtime import boundaries and re-export checks for the speech manifest."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import grimp
import pytest


@pytest.mark.parametrize(
    "importer",
    [
        "kaine.modules.audition.sherpa_stt",
        "kaine.modules.vox.sherpa_tts",
        "kaine.nexus.health.probes",
    ],
)
def test_speech_runtime_does_not_import_setup(importer: str) -> None:
    graph = grimp.build_graph("kaine")
    chains = graph.find_shortest_chains(
        importer=importer,
        imported="kaine.setup",
        as_packages=True,
    )
    assert not chains, (
        f"expected no import chains from {importer} to kaine.setup, "
        f"found {chains}"
    )


def test_setup_re_exports_speech_manifest_runtime_api() -> None:
    from kaine import speech_manifest
    from kaine.setup import speech_models

    assert speech_models.MANIFEST is speech_manifest.MANIFEST
    assert speech_models.is_installed is speech_manifest.is_installed


def test_setup_source_has_no_private_sha256_implementation() -> None:
    spec = importlib.util.find_spec("kaine.setup.speech_models")
    assert spec is not None
    assert spec.origin is not None
    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    ]
    assert "_sha256_file" not in functions
