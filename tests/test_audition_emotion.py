# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import sys
import types

import pytest

from kaine.modules.audition.emotion import (
    CATEGORIES,
    Emotion2vecClassifier,
    EmotionClassifier,
    EmotionResult,
    FakeEmotionClassifier,
    _normalize_label,
)


def test_categories_match_build_prompt():
    assert set(CATEGORIES) == {
        "neutral",
        "happy",
        "sad",
        "angry",
        "surprised",
        "fearful",
        "disgusted",
    }


def test_fake_satisfies_protocol():
    assert isinstance(FakeEmotionClassifier(), EmotionClassifier)


@pytest.mark.asyncio
async def test_fake_returns_scripted():
    happy = EmotionResult(
        category="happy",
        confidence=0.9,
        scores={c: (0.9 if c == "happy" else 0.0) for c in CATEGORIES},
        model="fake",
        latency_ms=1.0,
    )
    fake = FakeEmotionClassifier(results=[happy])
    out = await fake.classify(b"\x00", sample_rate=16000)
    assert out.category == "happy"
    assert out.confidence == 0.9


@pytest.mark.asyncio
async def test_fake_default_neutral_when_exhausted():
    fake = FakeEmotionClassifier()
    out = await fake.classify(b"\x00", sample_rate=16000)
    assert out.category == "neutral"
    assert out.confidence == 1.0


def test_normalize_label_aliases():
    assert _normalize_label("/happy/") == "happy"
    assert _normalize_label("Joy") == "happy"
    assert _normalize_label("Sadness") == "sad"
    assert _normalize_label("FEAR") == "fearful"
    assert _normalize_label("Unknown") == "neutral"


@pytest.mark.asyncio
async def test_emotion2vec_degrades_when_funasr_missing(monkeypatch):
    # Make `import funasr` fail.
    monkeypatch.setitem(sys.modules, "funasr", None)
    classifier = Emotion2vecClassifier()
    await classifier.load()
    assert classifier.funasr_available is False
    result = await classifier.classify(b"\x00" * 1024, sample_rate=16000)
    assert result.category == "neutral"
    assert result.confidence == 0.0
    assert result.raw.get("degraded") is True


@pytest.mark.asyncio
async def test_emotion2vec_load_idempotent_when_funasr_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "funasr", None)
    classifier = Emotion2vecClassifier()
    await classifier.load()
    await classifier.load()  # second load is a no-op
    assert classifier.funasr_available is False


@pytest.mark.asyncio
async def test_fake_shutdown():
    fake = FakeEmotionClassifier()
    await fake.shutdown()
    assert fake.shutdown_called is True


def test_fake_model_id_default():
    assert FakeEmotionClassifier().model_id == "fake/emotion"
