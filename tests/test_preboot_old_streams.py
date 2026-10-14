# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.bus.legacy_streams import OldStream
from kaine.preboot import PASS, SKIP, WARN, check_old_streams


@pytest.fixture
def keys_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")


@pytest.mark.asyncio
async def test_check_old_streams_warns_when_deletable_exist(keys_done):
    async def probe():
        return [
            OldStream(
                old=legacy_aliases.old_stream_name("sleep.out"),
                new="sleep.out",
                present=True,
                is_stream=True,
                length=3,
                memory_bytes=42,
            )
        ]

    results = await check_old_streams({}, probe=probe)
    assert len(results) == 1
    assert results[0].status == WARN
    assert results[0].name == "Old stream names"
    assert "python -m kaine.bus.legacy_streams --delete" in results[0].detail


@pytest.mark.asyncio
async def test_check_old_streams_passes_when_empty(keys_done):
    async def probe():
        return []

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == PASS
    assert results[0].detail == "no old-named streams remain"


@pytest.mark.asyncio
async def test_check_old_streams_warns_on_probe_error(keys_done):
    async def probe():
        raise RuntimeError("boom")

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == WARN
    assert results[0].detail == "could not check for old-named streams (RuntimeError)"


@pytest.mark.asyncio
async def test_check_old_streams_skips_when_keys_pending(monkeypatch):
    monkeypatch.setattr(legacy_names, "SCOPE_STATUS", {})

    async def probe():
        return []

    results = await check_old_streams({}, probe=probe)
    assert results[0].status == SKIP
    assert results[0].detail == "the keys rename has not run"
