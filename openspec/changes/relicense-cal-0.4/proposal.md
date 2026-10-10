## Why

KAINE ships the Cognitive Architecture License at version 0.2 (`LICENSE.md`, `NOTICE`, and `LicenseRef-CAL-0.4` in every source header), while the license repository, the welfare paper, the predictive-workspace paper and the website all describe version 0.4. Anyone checking the repository before MoC7 would find KAINE under an older and different text. Version 0.4 also leaves the governing law to "the jurisdiction where the Steward is established" without KAINE ever naming a Steward. The operator decided on 2026-10-10 to move KAINE to 0.4 and to name Kaine.One as Licensor and interim Steward under Oregon law.

## What Changes

- `LICENSE.md` becomes the CAL 0.4 text from kaineone/cognitive-architecture-license.
- Every `LicenseRef-CAL-0.4` identifier becomes `LicenseRef-CAL-0.4` (source headers, the header-application script, `pyproject.toml`, container and quadlet files, docs).
- `NOTICE` records version 0.4, that the text has not yet been reviewed by counsel, and an adoption notice: Licensor Kaine.One, interim Steward Kaine.One, governing law of the State of Oregon, United States, notices and Reciprocity License requests to kaine.one@tuta.com. It names the Steward, not the "Project Cooperative" of 0.2, as the grantor of Reciprocity Licenses.
- Docs that name the version (`THIRD_PARTY_LICENSES.md`, the glossary, the licence appendix, technology choices) say 0.4.

## Capabilities

### Modified Capabilities

- `license-compliance`: headers declare `LicenseRef-CAL-0.4`; `NOTICE` carries the adoption notice.

## Impact

- Licensing text and identifiers only. No runtime behaviour changes.
