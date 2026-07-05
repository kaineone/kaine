# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.audition.stt_client import (
    FakeSTTClient,
    SpeachesClient,
    STTClient,
)


def test_default_base_url():
    c = SpeachesClient()
    assert c.base_url == "http://127.0.0.1:8000"


def test_trailing_slash_stripped():
    c = SpeachesClient(base_url="http://x:8000/")
    assert c.base_url == "http://x:8000"


def test_fake_satisfies_protocol():
    assert isinstance(FakeSTTClient(), STTClient)


@pytest.mark.asyncio
async def test_fake_returns_scripted_in_order():
    fake = FakeSTTClient(responses=["one", "two"])
    a = await fake.transcribe(b"\x00", sample_rate=16000, model="m")
    b = await fake.transcribe(b"\x00", sample_rate=16000, model="m")
    c = await fake.transcribe(b"\x00", sample_rate=16000, model="m")
    assert a.text == "one"
    assert b.text == "two"
    assert "<fake-transcription>" in c.text


@pytest.mark.asyncio
async def test_fake_records_call_metadata():
    fake = FakeSTTClient()
    await fake.transcribe(b"\x00" * 1024, sample_rate=24000, model="m")
    assert fake.transcriptions == [(24000, 1024)]


@pytest.mark.asyncio
async def test_fake_aclose_marks_closed():
    fake = FakeSTTClient()
    await fake.aclose()
    assert fake.closed is True
