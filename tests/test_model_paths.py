# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The shared model-weights root and the per-model paths derived from it.

Model weights are redirected off the entity-state tree by ``$KAINE_MODELS_DIR``
(the container points it at the read-mostly ``kaine-models`` volume). Only the
ROOT moves — every per-model subdirectory name is stable so the setup phase that
writes and the runtime that reads agree, whether local or containerized.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from kaine import model_paths
from kaine.model_paths import DEFAULT_MODELS_DIR, MODELS_DIR_ENV_VAR, models_dir


def test_default_models_dir_is_local_state_models(monkeypatch):
    monkeypatch.delenv(MODELS_DIR_ENV_VAR, raising=False)
    assert models_dir() == Path("state/models")
    assert DEFAULT_MODELS_DIR == Path("state/models")


def test_models_dir_honors_env_override(monkeypatch):
    monkeypatch.setenv(MODELS_DIR_ENV_VAR, "/models")
    assert models_dir() == Path("/models")


def test_models_dir_read_per_call_not_cached(monkeypatch):
    monkeypatch.delenv(MODELS_DIR_ENV_VAR, raising=False)
    assert models_dir() == Path("state/models")
    monkeypatch.setenv(MODELS_DIR_ENV_VAR, "/elsewhere/models")
    assert models_dir() == Path("/elsewhere/models")


def test_weight_paths_default_under_local_state_models(monkeypatch):
    # With no override, every weight path keeps its historical state/models
    # location (subdir names unchanged) — an existing local download is not
    # orphaned by the containerization split.
    monkeypatch.delenv(MODELS_DIR_ENV_VAR, raising=False)

    from kaine.setup import abliteration_gate, organ
    from kaine.modules.topos import internvideo_next_loader

    assert organ.ORGAN_GGUF_DIR == Path("state/models/Qwen3.5-4B-abliterated-GGUF")
    assert (
        internvideo_next_loader.DEFAULT_WEIGHTS_DIR
        == Path("state/models/internvideo_next_base_p14_res224_f16")
    )
    assert (
        abliteration_gate.DEFAULT_VERDICT_PATH
        == Path("state/models/abliteration_verification.json")
    )
    # Each derives from the shared root — same parent as models_dir().
    assert organ.ORGAN_GGUF_DIR.parent == models_dir()
    assert internvideo_next_loader.DEFAULT_WEIGHTS_DIR.parent == models_dir()


def test_weight_paths_follow_container_models_root(monkeypatch):
    # Under the container's KAINE_MODELS_DIR=/models the SAME subdir names hang
    # off /models, so the model server's -m path and the loader agree.
    monkeypatch.setenv(MODELS_DIR_ENV_VAR, "/models")

    organ = importlib.reload(importlib.import_module("kaine.setup.organ"))
    loader = importlib.reload(
        importlib.import_module("kaine.modules.topos.internvideo_next_loader")
    )
    try:
        assert organ.ORGAN_GGUF_DIR == Path("/models/Qwen3.5-4B-abliterated-GGUF")
        assert organ.served_gguf_path() == Path(
            "/models/Qwen3.5-4B-abliterated-GGUF/KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
        )
        assert loader.DEFAULT_WEIGHTS_DIR == Path(
            "/models/internvideo_next_base_p14_res224_f16"
        )
    finally:
        # Restore the module-level constants to the default-env values so import
        # order cannot leak the override into other tests.
        monkeypatch.delenv(MODELS_DIR_ENV_VAR, raising=False)
        importlib.reload(importlib.import_module("kaine.setup.organ"))
        importlib.reload(
            importlib.import_module("kaine.modules.topos.internvideo_next_loader")
        )
        importlib.reload(model_paths)
