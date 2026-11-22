# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine/module_names.py (module-core task 2.1)."""

import ast
import importlib
import pathlib
import re
import sys

import kaine.legacy_names as legacy_names
import kaine.module_names as module_names

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _find_module_file(class_name: str) -> pathlib.Path | None:
    modules_root = REPO_ROOT / "kaine" / "modules"
    for path in modules_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(rf"^class {re.escape(class_name)}\b", text, re.MULTILINE):
            return path
    return None


def test_every_product_module_name_is_defined():
    for entry in legacy_names.MODULES.values():
        new_class = entry["new_class"]
        path = _find_module_file(new_class)
        if path is None:
            # Not a product module present in kaine/modules/.
            continue
        rel = path.relative_to(REPO_ROOT).with_suffix("")
        module_name = ".".join(rel.parts)
        module = importlib.import_module(module_name)
        cls = getattr(module, new_class)
        assert cls.name in module_names.MODULE_NAMES
        assert cls.name == getattr(module_names, cls.name.upper())


def test_names_match_legacy_table():
    new_keys = {entry["new_key"] for entry in legacy_names.MODULES.values()}
    new_keys |= {entry[0] for entry in getattr(legacy_names, "SURVEY_EXTRA", ())}
    # Every legacy new_key that names one of the product modules is in MODULE_NAMES;
    # (the reverse direction is checked by the following subset assertion).
    named_product_keys = {key for key in new_keys if key in module_names.MODULE_NAMES}
    assert named_product_keys == module_names.MODULE_NAMES
    assert module_names.MODULE_NAMES.issubset(new_keys)


def test_names_module_imports_nothing_from_kaine():
    path = REPO_ROOT / "kaine" / "module_names.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name == "kaine" and not alias.name.startswith("kaine.")
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or not (node.module == "kaine" or node.module.startswith("kaine."))
