# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class WhitelistEntry:
    """One allowed shell command.

    `arg_patterns` is one regex per arg position. A request must have
    exactly that many args, each matching its pattern. Empty
    `arg_patterns` means the command accepts no args.
    """
    command: str
    arg_patterns: tuple[str, ...] = field(default_factory=tuple)
    timeout_s: float = 5.0
    cwd: Optional[str] = None  # None → process default; otherwise must be an absolute path
    description: str = ""


class CommandWhitelist:
    def __init__(self, entries: Iterable[WhitelistEntry] = ()) -> None:
        self._entries: dict[str, WhitelistEntry] = {}
        for entry in entries:
            if not entry.command or any(ch in entry.command for ch in " \t\n;&|`"):
                raise ValueError(
                    f"whitelist entry command {entry.command!r} contains forbidden chars"
                )
            if entry.command in self._entries:
                raise ValueError(f"duplicate whitelist entry for {entry.command!r}")
            self._entries[entry.command] = entry

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, command: object) -> bool:
        return isinstance(command, str) and command in self._entries

    def get(self, command: str) -> Optional[WhitelistEntry]:
        return self._entries.get(command)

    def commands(self) -> list[str]:
        return sorted(self._entries.keys())

    def match(self, command: str, args: list[str]) -> Optional[WhitelistEntry]:
        """Return the matching entry, or None if disallowed."""
        entry = self._entries.get(command)
        if entry is None:
            return None
        if len(args) != len(entry.arg_patterns):
            return None
        for arg, pattern in zip(args, entry.arg_patterns):
            if not re.fullmatch(pattern, arg):
                return None
        return entry
