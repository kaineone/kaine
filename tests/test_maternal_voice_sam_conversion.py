# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Focused offline tests for the Sam-conversion slice of maternal voice.

These cover the contract surface that a future offline renderer must honor:
manifest format, Sam voice metadata, spectral-ceiling / level config, and the
no-intelligible-output prosody guards. They do not touch runtime or generator
code, and they do not render audio.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Maternal voice runtime module (manifest reader).
from kaine.modules.audition.maternal_voice import MANIFEST_FORMAT, VOICE_DATA_DIR

# Prosody gate checker (offline).
_spec = importlib.util.spec_from_file_location(
    "check_maternal_prosody",
    REPO_ROOT / "tools" / "maintainer" / "check_maternal_prosody.py",
)
prosody = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prosody)

# Offline generator (Chatterbox today; Sam target). Import constants only.
_gspec = importlib.util.spec_from_file_location(
    "generate_maternal_voice",
    REPO_ROOT / "tools" / "maintainer" / "generate_maternal_voice.py",
)
generator = importlib.util.module_from_spec(_gspec)
# Avoid running the heavy top-level side effects by loading constants via exec
# is not needed: module import only defines constants/functions (no render on import).
_gspec.loader.exec_module(generator)


def test_manifest_format_constant_is_one() -> None:
    assert MANIFEST_FORMAT == 1


@pytest.mark.skipif(
    not (VOICE_DATA_DIR / "manifest.json").exists(), reason="shipped manifest missing"
)
def test_manifest_format_contract_top_level() -> None:
    manifest = json.loads((VOICE_DATA_DIR / "manifest.json").read_text())
    required = {
        "format", "sample_rate", "initial_unlocked", "texts_sha256",
        "generator", "reference_voice", "items", "total_bytes", "total_seconds",
    }
    assert required.issubset(manifest.keys())
    assert manifest["format"] == MANIFEST_FORMAT
    assert manifest["sample_rate"] == 8000
    assert isinstance(manifest["items"], list) and manifest["items"]
    assert manifest["initial_unlocked"] == 5

    # Per-take contract.
    take_required = {"file", "sha256", "frames", "seconds", "seed", "rms_dbfs"}
    for item in manifest["items"]:
        assert {"id", "kind", "take_count", "text_sha256", "takes"}.issubset(item.keys()) or \
               {"id", "kind", "index", "text_sha256", "takes"}.issubset(item.keys())
        for take in item["takes"]:
            assert take_required.issubset(take.keys())
            assert take["file"].endswith(".flac")


def test_sam_voice_metadata_defaults() -> None:
    # Lazy import: qwen3_tts has heavy deps but instantiation does not load GPU.
    from kaine.modules.vocal.qwen3_tts import Qwen3TTS

    tts = Qwen3TTS()
    assert tts._model_id == "kaineone/Qwen3-TTS-Sam-0.6B"
    assert tts._speaker == "sam"


def test_spectral_ceiling_config_constants() -> None:
    # Offline post-processing contract that must survive the Sam conversion.
    assert generator.OUTPUT_SAMPLE_RATE == 8000
    assert generator.TARGET_RMS_DBFS == -20.0
    assert generator.PEAK_CEILING_DBFS == -1.0
    assert generator.TRIM_TOP_DB == 40.0
    assert generator.BASE_SEED == 20261018


def test_no_intelligible_output_guards() -> None:
    # Prosody-first / low-intelligibility content must pass; ordinary speech must not.
    nonsense = ("ma " * 150).strip()
    sentence = "The quick brown fox jumps over the lazy dog."
    assert prosody.check_prosody(nonsense) is True
    assert prosody.check_prosody(sentence) is False
    # Explicit thresholds from the render/plan gate.
    assert prosody.check_syllable_density(nonsense) is True
    assert prosody.consonant_transient_reduction(nonsense) >= prosody.MIN_TRANSIENT_REDUCTION
    assert prosody.syllable_density(nonsense) <= prosody.MAX_SYLLABLE_DENSITY
    # readability: prosody-first content stays below MAX_READABILITY
    assert prosody.flesch_reading_ease(nonsense) <= prosody.MAX_READABILITY or \
           prosody.check_readability(nonsense)


def test_texts_items_load_if_present() -> None:
    texts_path = VOICE_DATA_DIR / "texts.toml"
    if not texts_path.exists():
        pytest.skip("texts.toml missing")
    items = prosody.load_texts_items(texts_path)
    assert isinstance(items, list)
    # If items carry text, the gate must accept/reject consistently.
    for it in items:
        if "text" in it:
            result = prosody.check_text(it["text"])
            assert "ok" in result and "syllable_density" in result
