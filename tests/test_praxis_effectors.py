# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
import stat
from pathlib import Path

import pytest

from kaine.modules.praxis.effectors import (
    FileWriteEffector,
    FileWriteRequest,
    NotifyEffector,
    NotifyRequest,
    ShellEffector,
    ShellRequest,
)
from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry


@pytest.mark.asyncio
async def test_file_write_success(tmp_path: Path):
    sandbox = tmp_path / "sb"
    e = FileWriteEffector(sandbox)
    res = await e.act(FileWriteRequest(name="hello.txt", content="hi"))
    assert res.success is True
    assert (sandbox / "hello.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_file_write_rejects_absolute_path(tmp_path: Path):
    e = FileWriteEffector(tmp_path / "sb")
    res = await e.act(FileWriteRequest(name="/etc/passwd", content="oops"))
    assert res.success is False
    assert "sandbox" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_file_write_rejects_path_traversal(tmp_path: Path):
    e = FileWriteEffector(tmp_path / "sb")
    res = await e.act(FileWriteRequest(name="../../etc/passwd", content="x"))
    assert res.success is False
    assert "sandbox" in (res.error or "").lower()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_sandbox_dir_is_owner_only_under_permissive_umask(tmp_path: Path):
    """The file-write sandbox is created 0700 regardless of the ambient umask
    (P3 hardening, mirroring the snapshot dirs)."""
    old = os.umask(0o002)
    try:
        sandbox = tmp_path / "sb"
        e = FileWriteEffector(sandbox)
        res = await e.act(FileWriteRequest(name="hello.txt", content="hi"))
        assert res.success is True
        mode = stat.S_IMODE(sandbox.stat().st_mode)
        assert mode == 0o700, oct(mode)
    finally:
        os.umask(old)


@pytest.mark.asyncio
async def test_file_write_exceeding_max_bytes(tmp_path: Path):
    e = FileWriteEffector(tmp_path / "sb", max_bytes=5)
    res = await e.act(FileWriteRequest(name="big.txt", content="too large"))
    assert res.success is False
    assert "max_bytes" in (res.error or "")


@pytest.mark.asyncio
async def test_file_write_invalid_max_bytes():
    with pytest.raises(ValueError):
        FileWriteEffector("/tmp/sb", max_bytes=0)


@pytest.mark.asyncio
async def test_file_write_wrong_request_type(tmp_path: Path):
    e = FileWriteEffector(tmp_path / "sb")
    res = await e.act(NotifyRequest(title="x", body="y"))  # wrong shape
    assert res.success is False
    assert "FileWriteRequest" in (res.error or "")


@pytest.mark.asyncio
async def test_notify_log_fallback_writes_line(tmp_path: Path):
    log_path = tmp_path / "n.log"
    # Use a command name that doesn't exist on PATH so the fallback fires.
    e = NotifyEffector(
        notification_command="this-binary-does-not-exist-xyz",
        fallback_log_path=log_path,
    )
    res = await e.act(NotifyRequest(title="hello", body="world", urgency="low"))
    assert res.success is True
    assert res.metadata.get("transport") == "log-fallback"
    assert "hello" in log_path.read_text()


@pytest.mark.asyncio
async def test_notify_without_fallback_fails(tmp_path: Path):
    e = NotifyEffector(
        notification_command="this-binary-does-not-exist-xyz",
        fallback_log_path=None,
    )
    res = await e.act(NotifyRequest(title="x", body="y"))
    assert res.success is False


@pytest.mark.asyncio
async def test_shell_rejects_unknown_command():
    e = ShellEffector(CommandWhitelist())
    res = await e.act(ShellRequest(command="ls", args=[]))
    assert res.success is False
    assert "whitelist" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_shell_runs_whitelisted_command():
    wl = CommandWhitelist(
        [WhitelistEntry(command="echo", arg_patterns=("[A-Za-z0-9]+",), timeout_s=2.0)]
    )
    e = ShellEffector(wl)
    res = await e.act(ShellRequest(command="echo", args=["hello"]))
    assert res.success is True
    assert res.metadata.get("returncode") == 0


@pytest.mark.asyncio
async def test_shell_rejects_disallowed_arg():
    wl = CommandWhitelist(
        [WhitelistEntry(command="echo", arg_patterns=("[A-Za-z]+",), timeout_s=2.0)]
    )
    e = ShellEffector(wl)
    res = await e.act(ShellRequest(command="echo", args=["with space"]))
    assert res.success is False
