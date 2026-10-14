# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for docs/appendix-a-configuration/deprecated-names.md."""

import importlib.util
import pathlib
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_generator() -> types.ModuleType:
    path = REPO_ROOT / "tools" / "maintainer" / "gen_deprecated_names.py"
    spec = importlib.util.spec_from_file_location("gen_deprecated_names", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_deprecated_names"] = module
    spec.loader.exec_module(module)
    return module


def _load_table() -> types.ModuleType:
    path = REPO_ROOT / "tools" / "maintainer" / "rename_modules.py"
    spec = importlib.util.spec_from_file_location("rename_modules", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = module
    spec.loader.exec_module(module)
    return module.load_table(REPO_ROOT / "kaine" / "legacy_names.py")


GEN = _load_generator()
TABLE = _load_table()


@pytest.fixture(scope="session")
def table() -> types.ModuleType:
    return TABLE


def test_page_is_current(table: types.ModuleType) -> None:
    page = REPO_ROOT / "docs" / "appendix-a-configuration" / "deprecated-names.md"
    rendered = GEN.render(table)
    assert page.read_text(encoding="utf-8") == rendered, (
        "run `python tools/maintainer/gen_deprecated_names.py`"
    )


def test_page_lists_every_deprecated_name(table: types.ModuleType) -> None:
    page = GEN.render(table)
    assert table.ALIAS_LAST_RELEASE in page
    for entry in table.CONFIG_TABLES:
        assert f"`[{entry['old']}]`" in page
    for section in (table.CONFIG_KEYS, table.CONFIG_VALUES, table.ENV_VARS, table.CLI_FLAGS):
        for entry in section:
            assert f"`{entry['old']}`" in page


def test_check_mode_reports_a_stale_page(tmp_path: pathlib.Path, table: types.ModuleType) -> None:
    page = tmp_path / "docs" / "appendix-a-configuration" / "deprecated-names.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("stale\n", encoding="utf-8")
    table_path = REPO_ROOT / "kaine" / "legacy_names.py"

    check_argv = ["--check", "--root", str(tmp_path), "--table", str(table_path)]
    assert GEN.main(check_argv) == 1
    assert page.read_text(encoding="utf-8") == "stale\n"

    write_argv = ["--root", str(tmp_path), "--table", str(table_path)]
    assert GEN.main(write_argv) == 0
    assert page.read_text(encoding="utf-8") == GEN.render(table)
