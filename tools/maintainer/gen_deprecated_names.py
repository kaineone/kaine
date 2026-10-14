# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Render docs/appendix-a-configuration/deprecated-names.md from the rename table."""

import argparse
import importlib.util
import pathlib
import sys
import types


def _load_rename_modules() -> types.ModuleType:
    """Load ``rename_modules`` from the same directory via importlib."""
    path = pathlib.Path(__file__).resolve().parent / "rename_modules.py"
    spec = importlib.util.spec_from_file_location("rename_modules", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load rename_modules")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = module
    spec.loader.exec_module(module)
    return module


RENAME_MODULES = _load_rename_modules()

_TABLE_HEADER = "| Old | New | Last release that reads it |\n|---|---|---|"


def _require_old_new(entry: dict) -> None:
    """Validate that an entry has the required old/new keys."""
    if "old" not in entry or "new" not in entry:
        raise ValueError(f"entry missing old/new: {entry!r}")


def _row(old: str, new: str, release: str) -> str:
    """Return a Markdown table row."""
    return f"| `{old}` | `{new}` | {release} |"


def render(table) -> str:
    """Render the deprecated names appendix as Markdown."""
    R = table.ALIAS_LAST_RELEASE
    blocks: list[str] = []

    blocks.append(
        "# Deprecated names\n\n"
        "The names below are the configuration, environment and command names from before the module rename. "
        f"Each one is still read as its new name up to and including release {R}, and logs a deprecation line naming that release when it is used. "
        "Later releases stop reading them, so rename them in your files before then. "
        "[Module names](../appendix-e-module-names.md) maps each old module name to its new one.\n\n"
        "Plugin seams named after an old module (`oscillator.<old name>` or `<old name>.<seam>`) resolve to the new seam under the same rule."
    )

    # Configuration tables
    table_rows: list[str] = []
    for entry in table.CONFIG_TABLES:
        _require_old_new(entry)
        table_rows.append(f"| `[{entry['old']}]` | `[{entry['new']}]` | {R} |")
    blocks.append(
        "## Configuration tables\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(table_rows) if table_rows else "")
    )

    # Configuration keys
    seen_keys: set[tuple[str, str]] = set()
    key_rows: list[str] = []
    for entry in table.CONFIG_KEYS:
        _require_old_new(entry)
        key = (entry["old"], entry["new"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        key_rows.append(_row(entry["old"], entry["new"], R))
    blocks.append(
        "## Configuration keys\n\n"
        "A key keeps its new name in every table that uses it.\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(key_rows) if key_rows else "")
    )

    # Configuration values
    value_rows: list[str] = []
    for entry in table.CONFIG_VALUES:
        _require_old_new(entry)
        value_rows.append(_row(entry["old"], entry["new"], R))
    blocks.append(
        "## Configuration values\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(value_rows) if value_rows else "")
    )

    # Environment variables
    env_rows: list[str] = []
    for entry in table.ENV_VARS:
        _require_old_new(entry)
        env_rows.append(_row(entry["old"], entry["new"], R))
    blocks.append(
        "## Environment variables\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(env_rows) if env_rows else "")
    )

    # Command-line flags
    cli_rows: list[str] = []
    for entry in table.CLI_FLAGS:
        _require_old_new(entry)
        cli_rows.append(_row(entry["old"], entry["new"], R))
    blocks.append(
        "## Command-line flags\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(cli_rows) if cli_rows else "")
    )

    # Packages and commands
    seen_old: set[str] = set()
    pkg_rows: list[str] = []
    for entry in table.PACKAGING:
        _require_old_new(entry)
        kind = entry.get("kind")
        if kind == "pip_extra":
            old = f"kaine[{entry['old']}]"
            new = f"kaine[{entry['new']}]"
        elif kind in ("entry_point", "module_shim"):
            old = f"python -m {entry['old']}"
            new = f"python -m {entry['new']}"
        else:
            continue
        if old in seen_old:
            continue
        seen_old.add(old)
        pkg_rows.append(_row(old, new, R))
    blocks.append(
        "## Packages and commands\n\n"
        + _TABLE_HEADER
        + ("\n" + "\n".join(pkg_rows) if pkg_rows else "")
    )

    blocks.append(
        "The dashboard container and quadlet unit are renamed and are not read under their old names; see "
        "[Operator names](../appendix-e-module-names.md#operator-names) for the switch."
    )

    return "\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point for the generator script."""
    parser = argparse.ArgumentParser(description="Render the deprecated names appendix.")
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[2],
        help="repository root (where the page is written)",
    )
    parser.add_argument(
        "--table",
        type=pathlib.Path,
        default=None,
        help="path to kaine/legacy_names.py",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with an error if the page is not up to date",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    table_path = args.table if args.table else root / "kaine" / "legacy_names.py"
    table = RENAME_MODULES.load_table(table_path)

    page = root / "docs" / "appendix-a-configuration" / "deprecated-names.md"
    rendered = render(table)

    if args.check:
        current = page.read_text(encoding="utf-8") if page.exists() else ""
        if current != rendered:
            rel = page.relative_to(root) if page.is_relative_to(root) else page
            print(f"{rel} is out of date; run `python tools/maintainer/gen_deprecated_names.py`.")
            return 1
        return 0

    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
