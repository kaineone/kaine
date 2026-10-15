# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the deprecated dashboard command shim."""

import importlib
import importlib.util
import io

from kaine import legacy_names

_SHIM = next(
    e
    for e in legacy_names.PACKAGING
    if e["kind"] == "module_shim" and e["old"].count(".") == 1
)
OLD_MODULE = _SHIM["old"]
NEW_MODULE = _SHIM["new"]


def test_shim_warns_and_delegates(monkeypatch):
    shim = importlib.import_module(OLD_MODULE + ".__main__")
    calls = []

    def fake_main():
        calls.append(True)
        return 7

    monkeypatch.setattr(shim, "_main", fake_main)
    err = io.StringIO()
    result = shim.main(err=err)

    assert result == 7
    assert calls == [True]
    assert err.getvalue() == (
        f"python -m {OLD_MODULE} is deprecated; run python -m {NEW_MODULE} instead\n"
    )


def test_shim_is_importable():
    assert importlib.util.find_spec(OLD_MODULE + ".__main__") is not None
    assert NEW_MODULE.startswith("kaine.")
    assert importlib.util.find_spec(NEW_MODULE + ".__main__") is not None
