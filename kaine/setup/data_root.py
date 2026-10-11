# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""``python -m kaine.setup.data_root root`` prints the configured data root.

Used by the native service scripts (scripts/lib/native-services.sh) to place
native Redis and Qdrant data under ``[storage].data_root`` / ``KAINE_DATA_ROOT``.
Prints nothing when no data root is configured or the config cannot be loaded.
"""
from __future__ import annotations

import sys

from kaine.storage import configured_data_root


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["root"]:
        try:
            from kaine.config import load_kaine_config

            config = load_kaine_config()
        except Exception:
            # No readable config: the caller falls back to the checkout.
            return 0
        root = configured_data_root(config)
        if root is not None:
            print(root)
        return 0
    print("usage: python -m kaine.setup.data_root root", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
