# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Map module keys to their current Python package/identifier names.

Some modules have moved to new packages (for example ``vision`` and ``sequence``)
while their module keys still use the old names. The helpers here translate
between keys and the on-disk package name used in ``kaine.modules``.
"""

from pathlib import Path

from kaine import legacy_names

_MODULES_DIR = Path(__file__).resolve().parents[1] / "kaine" / "modules"


def identifier_for_key(key: str) -> str:
    """The package and identifier name of the module with this key.

    The new key when that module has already moved under it, else the key.
    Accepts both package directories and single-file modules.
    """
    new = legacy_names.MODULES.get(key, {}).get("new_key", key)
    # __init__.py distinguishes real packages from stale dirs; .py covers single-file modules.
    if new != key and (
        (_MODULES_DIR / new / "__init__.py").is_file()
        or (_MODULES_DIR / f"{new}.py").is_file()
    ) and not (
        (_MODULES_DIR / key / "__init__.py").is_file()
        or (_MODULES_DIR / f"{key}.py").is_file()
    ):
        return new
    return key


def key_for_identifier(name: str) -> str:
    """The module key for a package or identifier name (inverse of identifier_for_key)."""
    if legacy_names.SCOPE_STATUS.get("keys") == "done":
        return name
    for key, entry in legacy_names.MODULES.items():
        if entry.get("new_key") == name and identifier_for_key(key) == name:
            return key
    return name
