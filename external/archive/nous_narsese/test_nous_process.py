"""Subprocess wrapper tests.

The pure logic is exercised against FakeNARProcess. A separate opt-in test
launches the real binary when KAINE_NOUS_RUN_REAL_NAR=1.
"""
import os
import pathlib

import pytest

from kaine.modules.nous.process import (
    FakeNARProcess,
    NARProcess,
    NARProcessProtocol,
)


def test_fake_satisfies_protocol():
    assert isinstance(FakeNARProcess(), NARProcessProtocol)


@pytest.mark.asyncio
async def test_fake_lifecycle():
    p = FakeNARProcess()
    assert not p.running
    await p.start()
    assert p.running
    assert p.returncode is None
    await p.stop()
    assert not p.running
    assert p.returncode == 0


@pytest.mark.asyncio
async def test_fake_send_and_step_record():
    p = FakeNARProcess()
    await p.start()
    await p.send("<a --> b>. :|:")
    p.scripted_lines.append(
        [
            "Input: <a --> b>. :|: Priority=1 Stamp=[1] Truth: frequency=1.0, confidence=0.9",
            "Derived: <a --> c>. Priority=0.3 Stamp=[1,2] Truth: frequency=1.0, confidence=0.45",
            "done with 5 additional inference steps.",
        ]
    )
    lines = await p.step(5)
    assert p.sent == ["<a --> b>. :|:"]
    assert p.step_calls == 1
    assert any("Derived:" in line for line in lines)


@pytest.mark.asyncio
async def test_fake_send_when_not_running_raises():
    p = FakeNARProcess()
    with pytest.raises(RuntimeError):
        await p.send("foo")


@pytest.mark.asyncio
async def test_fake_force_exit_marks_returncode():
    p = FakeNARProcess()
    await p.start()
    p.force_exit(returncode=7)
    assert not p.running
    assert p.returncode == 7


REAL_NAR_ENV = "KAINE_NOUS_RUN_REAL_NAR"
NAR_BIN = pathlib.Path("external/OpenNARS-for-Applications/NAR")


@pytest.mark.skipif(
    os.environ.get(REAL_NAR_ENV) != "1" or not NAR_BIN.exists(),
    reason=f"set {REAL_NAR_ENV}=1 and run scripts/build-ona.sh to enable",
)
@pytest.mark.asyncio
async def test_real_nar_roundtrip():
    proc = NARProcess(str(NAR_BIN))
    await proc.start()
    try:
        assert proc.running
        await proc.send("<bird --> animal>. :|:")
        await proc.send("<bird --> flier>. :|:")
        lines = await proc.step(5)
        assert any("Derived:" in line or "Selected:" in line for line in lines)
    finally:
        await proc.stop()
        assert not proc.running
