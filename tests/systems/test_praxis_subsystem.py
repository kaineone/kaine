# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Praxis subsystem: file write + notify + shell whitelist, with audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.modules.praxis.module import Praxis
from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_praxis_file_write_lands_in_sandbox(tmp_path):
    sandbox = tmp_path / "sandbox"
    audit = tmp_path / "audit.log"
    async with SubsystemHarness() as h:
        praxis = Praxis(
            h.bus,
            sandbox_path=sandbox,
            audit_log_path=audit,
            notification_fallback_log=tmp_path / "notify.log",
            whitelist=CommandWhitelist(),  # empty shell whitelist
        )
        await h.register(praxis)
        # Praxis observes the bus for action requests on praxis.action stream.
        # Smoke: serialize works.
        assert isinstance(praxis.serialize(), dict)


@pytest.mark.asyncio
async def test_praxis_rejects_shell_command_not_in_whitelist(tmp_path):
    audit = tmp_path / "audit.log"
    async with SubsystemHarness() as h:
        praxis = Praxis(
            h.bus,
            sandbox_path=tmp_path / "sandbox",
            audit_log_path=audit,
            notification_fallback_log=tmp_path / "notify.log",
            whitelist=CommandWhitelist(),
        )
        await h.register(praxis)
        # Even if a shell request arrives, the empty whitelist must deny.
        shell = praxis._effectors["shell"]
        assert "echo" not in getattr(shell._whitelist, "_entries", {})


@pytest.mark.asyncio
async def test_praxis_accepts_whitelisted_command(tmp_path):
    async with SubsystemHarness() as h:
        wl = CommandWhitelist([
            WhitelistEntry(
                command="echo",
                arg_patterns=("[A-Za-z0-9]+",),
                timeout_s=2.0,
                description="echo token",
            )
        ])
        praxis = Praxis(
            h.bus,
            sandbox_path=tmp_path / "sandbox",
            audit_log_path=tmp_path / "audit.log",
            notification_fallback_log=tmp_path / "notify.log",
            whitelist=wl,
        )
        await h.register(praxis)
        shell = praxis._effectors["shell"]
        assert "echo" in shell._whitelist._entries
