## Why

`pyproject.toml` declares the licence with the table form `license = { file = "LICENSE.md" }` and keeps the SPDX identifier only in a comment. PEP 639 replaced that form: `project.license` is now a string holding an SPDX licence expression, which becomes the `License-Expression` core metadata field, and `project.license-files` lists the legal files to ship, each becoming a `License-File` field. The table subkeys are deprecated, and setuptools, the declared backend (`setuptools>=84.0.0`), has warned about the table form since v77.0.0. A built wheel therefore carries no machine-readable licence expression, and `NOTICE` and `THIRD_PARTY_LICENSES.md` reach a distribution only through setuptools' default filename patterns rather than through a declaration.

## What Changes

- `project.license` becomes the SPDX expression `"LicenseRef-CAL-0.4"`, the identifier every source header already carries.
- `project.license-files` lists `LICENSE.md`, `NOTICE` and `THIRD_PARTY_LICENSES.md`, the three legal files at the repository root.
- No `License ::` trove classifier is declared. The manifest has no classifiers today; the requirement keeps it that way, because the packaging specification lets a build tool reject a `License ::` classifier next to a licence expression and the PEP deprecates them.
- The package-manifest test builds its wheel from a copy that includes all three licence files, and a new test reads the built wheel's core metadata.

## Capabilities

### Modified Capabilities

- `package-manifest`: the built distributions declare the licence as an SPDX expression and carry the declared licence files.

## Impact

- **Code:** `pyproject.toml`, `tests/test_package_manifest.py`.
- **Behaviour:** the wheel's `METADATA` gains `License-Expression: LicenseRef-CAL-0.4` and one `License-File` line per declared file, and loses the `License` field that carried the whole text of `LICENSE.md`. The licence files sit under `.dist-info/licenses/`. Nothing at runtime changes.
- **Build:** no new requirement; setuptools 77.0.0 and later support both keys, and the build already requires 84.0.0.
- **Out of scope:** `plugins/kaine-cl1/pyproject.toml` still uses `license = { text = ... }` and is a separate package with its own release.
