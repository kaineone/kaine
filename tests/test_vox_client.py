# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.vox.client import (
    ChatterboxClient,
    FakeTTSClient,
    TTSClient,
    TTSRequest,
)


def test_default_base_url():
    c = ChatterboxClient()
    assert c.base_url == "http://127.0.0.1:8883"


def test_trailing_slash_stripped():
    c = ChatterboxClient(base_url="http://x:8883/")
    assert c.base_url == "http://x:8883"


def test_fake_satisfies_protocol():
    assert isinstance(FakeTTSClient(), TTSClient)


@pytest.mark.asyncio
async def test_fake_returns_canned_audio():
    fake = FakeTTSClient(canned_audio=b"\x00\x01\x02")
    result = await fake.synthesize(TTSRequest(text="hi"))
    assert result.audio == b"\x00\x01\x02"
    assert result.bytes_produced == 3
    assert result.output_format == "wav"


@pytest.mark.asyncio
async def test_fake_records_requests():
    fake = FakeTTSClient()
    await fake.synthesize(TTSRequest(text="one"))
    await fake.synthesize(TTSRequest(text="two", output_format="mp3"))
    assert len(fake.requests) == 2
    assert fake.requests[0].text == "one"
    assert fake.requests[1].output_format == "mp3"


@pytest.mark.asyncio
async def test_fake_aclose_marks_closed():
    fake = FakeTTSClient()
    await fake.aclose()
    assert fake.closed is True


def test_tts_request_defaults():
    r = TTSRequest(text="hi")
    assert r.voice_mode == "predefined"
    assert r.output_format == "wav"
    assert r.split_text is True
    assert r.temperature is None  # passes through to server default
