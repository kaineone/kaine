# Package manifest

## Why
`pyproject.toml` listed its packages by hand, and the list has not changed since the first public release. A wheel built from it misses 24 of the 47 packages under `kaine/` (among them `kaine.boot`, `kaine.distributed` and the benchmark runners). It would also ship Nexus without its fonts or its vendored JavaScript, so the interface would render broken. Every install today is editable, which is why nothing has failed yet. Any non-editable install, including the easy-install path for finished entities, would break.

## What changes
- Packages are discovered (`kaine*`) instead of listed.
- Package data covers every runtime file: Nexus templates, styles, scripts, fonts and vendored libraries; Hypnos's probe set; Eidolon's surname list; and any `*.jinja` template.
- A test builds the real wheel from a clean copy of the source and checks that it carries every package and every non-documentation file under `kaine/`.

## Impact
- Specs: a new `package-manifest` capability.
- Code: `pyproject.toml` and `tests/test_package_manifest.py`.
- Research impact: none. Editable installs, which every study uses, are unchanged.
