# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Deprecated alias for :mod:`kaine.lifecycle.episodic_memory_recover`.

Kept so the operator recovery command keeps working. This shim will be removed by the functional-module-names-drop-aliases change.
"""

from __future__ import annotations

import sys

from kaine.lifecycle.episodic_memory_recover import main as _main

NEW_COMMAND = "python -m kaine.lifecycle.episodic_memory_recover"


def main(argv: list[str] | None = None, *, out=None, err=None) -> int:
    """Print one deprecation line naming the new command, then run it unchanged."""
    stream = err if err is not None else sys.stderr
    stream.write(f"kaine.lifecycle.mnemos_recover is deprecated; run {NEW_COMMAND} instead\n")
    return _main(argv, out=out, err=err)


if __name__ == "__main__":
    sys.exit(main())
