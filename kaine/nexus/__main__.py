# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Deprecated alias for ``python -m kaine.dashboard``.

Kept so ``python -m kaine.nexus`` keeps working until the operator rename step. This shim will be removed by the functional-module-names-drop-aliases change.
"""

from __future__ import annotations

import sys

from kaine.dashboard.__main__ import main as _main

NEW_COMMAND = "python -m kaine.dashboard"


def main(*, err=None) -> int:
    """Print one deprecation line naming the new command, then run it unchanged."""
    stream = err if err is not None else sys.stderr
    stream.write(f"python -m kaine.nexus is deprecated; run {NEW_COMMAND} instead\n")
    return _main()


if __name__ == "__main__":
    sys.exit(main())
