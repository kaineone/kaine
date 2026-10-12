## 1. Licence metadata

- [x] 1.1 `pyproject.toml`: `license = "LicenseRef-CAL-0.4"` and `license-files = ["LICENSE.md", "NOTICE", "THIRD_PARTY_LICENSES.md"]`; no `License ::` classifier.
- [x] 1.2 `tests/test_package_manifest.py`: build from a copy that includes the three licence files, and assert the wheel's `METADATA` has `License-Expression: LicenseRef-CAL-0.4`, a `License-File` line for each file, no `License` field and no `License ::` classifier, with the files under `.dist-info/licenses/`.

## 2. Verification

- [x] 2.1 Build an sdist and a wheel into a temporary directory and read both core metadata files.
- [x] 2.2 The build prints no deprecation warning about the licence.
- [x] 2.3 The package-manifest and extras tests pass, and `preflight-gate.sh` is green.
- [x] 2.4 `openspec validate pep639-license-fields --strict`.
