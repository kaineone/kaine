# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry


def test_empty_whitelist_rejects_everything():
    wl = CommandWhitelist()
    assert wl.match("echo", []) is None
    assert wl.match("ls", []) is None


def test_match_with_no_args():
    wl = CommandWhitelist([WhitelistEntry(command="true")])
    assert wl.match("true", []) is not None
    assert wl.match("true", ["hi"]) is None  # wrong arity


def test_match_with_arg_patterns():
    wl = CommandWhitelist(
        [WhitelistEntry(command="echo", arg_patterns=("[A-Za-z0-9]+",))]
    )
    assert wl.match("echo", ["hello"]) is not None
    assert wl.match("echo", ["with space"]) is None
    assert wl.match("echo", ["bad; rm -rf /"]) is None


def test_unknown_command_rejected():
    wl = CommandWhitelist([WhitelistEntry(command="echo")])
    assert wl.match("ls", []) is None


def test_disallow_command_with_shell_metachars():
    with pytest.raises(ValueError):
        CommandWhitelist([WhitelistEntry(command="echo;ls")])


def test_duplicate_command_rejected():
    with pytest.raises(ValueError):
        CommandWhitelist(
            [WhitelistEntry(command="echo"), WhitelistEntry(command="echo")]
        )


def test_contains_and_get():
    wl = CommandWhitelist([WhitelistEntry(command="echo")])
    assert "echo" in wl
    assert "ls" not in wl
    assert wl.get("echo") is not None
    assert wl.get("ls") is None


def test_commands_listing():
    wl = CommandWhitelist(
        [WhitelistEntry(command="b"), WhitelistEntry(command="a")]
    )
    assert wl.commands() == ["a", "b"]
