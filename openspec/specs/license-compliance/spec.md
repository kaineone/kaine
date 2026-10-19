# license-compliance Specification

## Purpose
This capability requires every shipped first-party Python file to carry an SPDX license header and copyright line, and adds NOTICE and contributor terms, with the test suite checking header presence. It applies to files under kaine/, scripts/, tests/, and the repository top level, while exempting vendored third-party code under external/.

## Requirements

### Requirement: SPDX license header on every shipped source file
Every shipped first-party Python source file SHALL begin with a license header declaring
`SPDX-License-Identifier: LicenseRef-CAL-0.5` and a copyright line. This covers files under
`kaine/`, `scripts/`, `tests/`, and the repository top level. Vendored third-party code under
`external/` is exempt and
SHALL retain its upstream headers. The header SHALL be applied by an idempotent script (re-runnable
as files are added) and SHALL sit above the module docstring, after any shebang line.

#### Scenario: Shipped file carries the header
- **WHEN** any first-party `.py` under `kaine/`, `scripts/`, `tests/`, or the top level is inspected
- **THEN** its first non-shebang lines declare `SPDX-License-Identifier: LicenseRef-CAL-0.5` and a
  copyright line

#### Scenario: Vendored code is exempt
- **WHEN** a file under `external/` is inspected
- **THEN** it is not required to carry the CAL header and retains its upstream license header

#### Scenario: Re-applying is a no-op
- **WHEN** the header-application script is run a second time
- **THEN** no file is modified (headers are not duplicated)

### Requirement: NOTICE and contributor terms
The repository SHALL include a root `NOTICE` file recording the CAL version and status, an adoption notice naming the Licensor, the Steward, the governing law and the address for notices, the
copyright, the reference to the Intrinsic Values required by CAL Article 6.1, and third-party
attributions. `docs/21-contributing.md` SHALL state that inbound contributions are licensed under CAL
and are subject to the Article 4 entity-welfare obligations.

#### Scenario: NOTICE present
- **WHEN** the repository root is inspected
- **THEN** a `NOTICE` file exists referencing CAL 0.5, the adoption notice, the copyright, the Intrinsic Values, and
  third-party attributions

#### Scenario: Contributor terms stated
- **WHEN** `docs/21-contributing.md` is read
- **THEN** it states that contributions are licensed under CAL and subject to the welfare obligations

### Requirement: Header presence is enforced by the test suite
The test suite SHALL include a check that fails if any shipped first-party `.py` lacks the SPDX
header, so the header set cannot silently rot.

#### Scenario: Missing header fails the suite
- **WHEN** a shipped first-party `.py` is added without the SPDX header
- **THEN** the license-header test fails, naming the offending file

### Requirement: Vendored fonts carry their notices
Every font file shipped under `kaine/dashboard/static/fonts/` SHALL be credited
in `THIRD_PARTY_LICENSES.md` with its copyright line, licence and upstream
source, and SHALL be covered by a licence file in the same folder that holds
its copyright line and the full licence text. `THIRD_PARTY_LICENSES.md` SHALL
NOT list a font file that is not on disk. A test SHALL enforce both.

#### Scenario: A shipped font is credited and licensed
- **WHEN** a font file is present under `kaine/dashboard/static/fonts/`
- **THEN** `THIRD_PARTY_LICENSES.md` names it, and a licence file in that folder
  carries its copyright line and the SIL Open Font License text

#### Scenario: A listed font is missing
- **WHEN** `THIRD_PARTY_LICENSES.md` lists a font file that does not exist
- **THEN** the font-notices test fails, naming the file
