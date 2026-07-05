## Why

KAINE is licensed under the Cognitive Architecture License (CAL), but the codebase does not yet
carry or enforce it: 0 of ~378 first-party `.py` files have a license/SPDX header, there is no
`NOTICE` file (CAL Article 6.1 requires keeping copyright/license notices and the reference to the
Intrinsic Values in all copies), `docs/contributing.md` has no contributor-licensing clause, and
there is no check that keeps headers from rotting. Dependency licenses are already clean (the one
GPL risk, `parselmouth`, was deliberately swapped for ISC `librosa`), so this change is about making
the project's *own* code visibly and enforceably carry CAL.

## What Changes

- Every first-party `.py` file (under `kaine/`, `scripts/`, `tests/`, and top-level; **excluding**
  vendored `external/` which keeps its upstream MIT headers, and `.venv`/build artifacts) SHALL
  begin with a two-line header: `# SPDX-License-Identifier: LicenseRef-CAL-0.2` and
  `# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>` (LicenseRef per the SPDX convention for a
  non-standard license). Applied by an idempotent script so it is re-runnable as files are added.
- A root `NOTICE` file SHALL state the CAL reference and draft status, the copyright, the
  Article 6.1-required reference to the Intrinsic Values, and the third-party attributions
  (DreamerV3 MIT, OpenNARS MIT).
- `docs/contributing.md` SHALL gain contributor-licensing terms (inbound contributions are licensed
  under CAL and are subject to the Article 4 entity-welfare obligations; a sign-off line).
- `docs/licenses.md` SHALL consolidate the dependency-license review (already in
  `docs/tech-choices.md`), note the deliberate GPL→ISC swap, and record model/weight licenses
  (including a Chatterbox line).
- A `scripts/check_license_headers.py` + `tests/test_license_headers.py` SHALL assert every shipped
  first-party `.py` carries the SPDX header, matching the repo's test-driven (CI-less) style, so the
  header set cannot silently rot.
- `pyproject.toml` keeps `license = {file = "LICENSE.md"}` with a clarifying `LicenseRef-CAL-0.2`
  note.

## Capabilities

### New Capabilities

- `license-compliance`: per-file SPDX headers on all shipped source, a root NOTICE, contributor
  terms, and an enforcement test.

## Impact

- **Code**: a two-line header prepended to ~378 `.py` files (no logic change); new
  `scripts/apply_license_headers.py`, `scripts/check_license_headers.py`,
  `tests/test_license_headers.py`.
- **Docs**: new `NOTICE`, `docs/licenses.md`; `docs/contributing.md` contributor terms;
  `pyproject.toml` note.
- **No runtime behavior change.** Headers are comments; the enforcement test runs in the suite.
