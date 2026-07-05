# Tasks

## 1. Header tooling
- [ ] 1.1 `scripts/apply_license_headers.py` — idempotent: prepend the two-line SPDX+copyright header to every first-party `.py` (kaine/, scripts/, tests/, top-level) that lacks it; SKIP `external/`, `.venv/`, build dirs; preserve shebangs (header goes after a `#!` line) and put the header above the module docstring; never double-apply.
- [ ] 1.2 `scripts/check_license_headers.py` — exit non-zero listing any first-party `.py` missing the header (same coverage/skip rules); importable helper reused by the test.

## 2. Apply headers
- [ ] 2.1 Run `apply_license_headers.py`; ~378 files gain the header. No logic changes.

## 3. NOTICE + docs
- [ ] 3.1 Root `NOTICE` — CAL reference + draft status, copyright, Article 6.1 Intrinsic-Values reference, third-party attributions (DreamerV3 MIT, OpenNARS MIT).
- [ ] 3.2 `docs/contributing.md` — contributor-licensing terms (inbound=outbound under CAL; Article 4 welfare obligations; sign-off line).
- [ ] 3.3 `docs/licenses.md` — dependency-license manifest consolidating tech-choices.md; GPL→ISC swap note; model/weight licenses incl. Chatterbox.
- [ ] 3.4 `pyproject.toml` — add a `LicenseRef-CAL-0.2` clarifying note (keep `license = {file = "LICENSE.md"}`).

## 4. Enforcement test
- [ ] 4.1 `tests/test_license_headers.py` — assert every shipped first-party `.py` has the SPDX header (via the checker); assert `NOTICE` exists.

## 5. Verify
- [ ] 5.1 `.venv/bin/pytest -q -p no:cacheprovider` green (incl. the new header test).
- [ ] 5.2 `python scripts/check_license_headers.py` exits 0; re-running `apply_license_headers.py` is a no-op (idempotent).
- [ ] 5.3 `openspec validate cal-license-compliance --strict` passes.
