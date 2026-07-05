"""Subprocess wrapper around the ONA NAR binary.

`NARProcess` runs the real binary; `FakeNARProcess` is a test double. Both
satisfy `NARProcessProtocol` so `Nous` can be tested without the binary.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class NARProcessProtocol(Protocol):
    @property
    def running(self) -> bool: ...

    @property
    def returncode(self) -> Optional[int]: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, line: str) -> None: ...

    async def step(self, n: int) -> list[str]:
        """Ask NAR to perform `n` inference steps. Returns the lines NAR
        emitted between the step request and its 'done with N additional
        inference steps.' acknowledgement."""


class NARProcess:
    """Real ONA subprocess wrapper using asyncio.create_subprocess_exec."""

    def __init__(
        self,
        binary_path: str,
        *,
        startup_timeout_s: float = 5.0,
        step_timeout_s: float = 10.0,
    ) -> None:
        self._binary_path = binary_path
        self._startup_timeout_s = startup_timeout_s
        self._step_timeout_s = step_timeout_s
        self._proc: Optional[asyncio.subprocess.Process] = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def returncode(self) -> Optional[int]:
        if self._proc is None:
            return None
        return self._proc.returncode

    async def start(self) -> None:
        if self.running:
            return
        self._proc = await asyncio.create_subprocess_exec(
            self._binary_path,
            "shell",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def stop(self) -> None:
        if not self.running or self._proc is None:
            return
        try:
            self._proc.stdin.write(b"quit\n")  # type: ignore[union-attr]
            await self._proc.stdin.drain()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            log.warning("NAR did not exit after `quit`; sending terminate")
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                log.warning("NAR ignored terminate; sending kill")
                self._proc.kill()
                await self._proc.wait()
        self._proc = None

    async def send(self, line: str) -> None:
        if not self.running or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("NAR process not running")
        if not line.endswith("\n"):
            line += "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()

    async def step(self, n: int) -> list[str]:
        if not self.running or self._proc is None or self._proc.stdout is None:
            raise RuntimeError("NAR process not running")
        n = max(0, int(n))
        await self.send(str(n))
        sentinel = f"done with {n} additional inference steps."
        lines: list[str] = []
        async def _read_until_sentinel() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            while True:
                raw = await self._proc.stdout.readline()
                if not raw:
                    return
                text = raw.decode("utf-8", errors="replace").rstrip("\n")
                if sentinel in text:
                    return
                lines.append(text)
        try:
            await asyncio.wait_for(_read_until_sentinel(), timeout=self._step_timeout_s)
        except asyncio.TimeoutError:
            log.warning("NAR step(%d) timed out after %ss", n, self._step_timeout_s)
        return lines


class FakeNARProcess:
    """Scriptable in-memory stand-in for tests.

    Append lines to `scripted_lines` and they'll be returned by the next
    `step()` call. Useful for asserting Nous's behavior without launching
    the real NAR binary.
    """

    def __init__(self) -> None:
        self._running = False
        self._returncode: Optional[int] = None
        self.sent: list[str] = []
        self.scripted_lines: list[list[str]] = []
        self.step_calls = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def returncode(self) -> Optional[int]:
        return self._returncode

    async def start(self) -> None:
        self._running = True
        self._returncode = None

    async def stop(self) -> None:
        self._running = False
        self._returncode = 0

    async def send(self, line: str) -> None:
        if not self._running:
            raise RuntimeError("FakeNARProcess not running")
        self.sent.append(line.rstrip("\n"))

    async def step(self, n: int) -> list[str]:
        if not self._running:
            raise RuntimeError("FakeNARProcess not running")
        self.step_calls += 1
        if self.scripted_lines:
            return self.scripted_lines.pop(0)
        return []

    def force_exit(self, returncode: int = 1) -> None:
        """Simulate an unexpected NAR crash."""
        self._running = False
        self._returncode = returncode
