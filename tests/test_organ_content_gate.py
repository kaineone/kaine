# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Boot-time organ content-probe gate (kaine.setup.organ.verify_organ_generates).

The gate is the preventive for a served-but-MUTE organ: a hybrid-thinking model
whose chain-of-thought is not suppressed returns empty content yet passes the
served-alias check, so the entity would boot voiceless. These tests pin the three
verdicts — speaks / mute / unreachable — through an injected chat client, so no
live model server is required.
"""
from __future__ import annotations

from kaine.modules.lingua.client import FakeChatClient
from kaine.setup.organ import verify_organ_generates


async def test_gate_passes_when_organ_returns_content():
    fake = FakeChatClient(responses=["Hello"])
    result = await verify_organ_generates("http://x/v1", "organ", client=fake)
    assert result.ok is True
    assert "Hello" in result.sample
    # the probe sent exactly one completion through the real client contract
    assert len(fake.requests) == 1
    # an injected client is the caller's to close — the gate must not close it
    assert fake.closed is False


async def test_gate_fails_when_organ_is_mute_empty_content():
    fake = FakeChatClient(responses=[""])
    result = await verify_organ_generates("http://x/v1", "organ", client=fake)
    assert result.ok is False
    assert "MUTE" in result.detail
    # the remediation points at the real cause (thinking not suppressed)
    assert "enable_thinking" in result.detail


async def test_gate_fails_when_organ_returns_whitespace_only():
    fake = FakeChatClient(responses=["   \n  "])
    result = await verify_organ_generates("http://x/v1", "organ", client=fake)
    assert result.ok is False


async def test_gate_fails_when_organ_unreachable():
    class _Raising:
        base_url = "http://x/v1"

        async def complete(self, request):
            raise ConnectionError("connection refused")

        async def aclose(self):
            pass

    result = await verify_organ_generates("http://x/v1", "organ", client=_Raising())
    assert result.ok is False
    assert "did not respond" in result.detail
    assert "ConnectionError" in result.detail
