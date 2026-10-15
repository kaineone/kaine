## Why

Version 0.5 of the Cognitive Architecture License is released in kaineone/cognitive-architecture-license, together with the rewritten licence paper and the website's licence page. KAINE still ships the 0.4 text and declares `LicenseRef-CAL-0.4`, so anyone checking the repository would find it under an older text than the one the project presents. Version 0.5 keeps every protection of 0.4, makes each obligation a condition of the grant, and assigns the Entity duties to Operators, with the Steward as caretaker of last resort. The operator gave the all clear for the 0.5 release on 2026-10-14 and asked for KAINE to move to it.

## What Changes

- `LICENSE.md` becomes the CAL 0.5 text from kaineone/cognitive-architecture-license.
- Every `LicenseRef-CAL-0.4` identifier becomes `LicenseRef-CAL-0.5`: source headers, the header-application and header-check scripts, both `pyproject.toml` files, container and quadlet files, and docs.
- `NOTICE` records version 0.5. Its adoption notice keeps Kaine.One as Licensor and Steward under Oregon law, citing CAL Articles 1 and 10.4 instead of the 0.4 interim-Steward reference, and its summary of the free-use terms and the Intrinsic Values follows the 0.5 text.
- Docs that name the version say 0.5.
- The completed changes `relicense-cal-0.4` and `pep639-license-fields` are archived first, so the main specs carry 0.4 before this change moves them to 0.5.

## Capabilities

### Modified Capabilities

- `license-compliance`: headers declare `LicenseRef-CAL-0.5`; `NOTICE` references CAL 0.5.
- `package-manifest`: the licence expression is `LicenseRef-CAL-0.5`.

## Impact

- Licensing text and identifiers only. No runtime behaviour changes.
- Archived changes and the rename-module test fixtures keep their historical identifiers.
