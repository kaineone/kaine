# license-compliance Specification

## Purpose
TBD - created by archiving change cal-license-compliance. Update Purpose after archive.
## Requirements
### Requirement: SPDX license header on every shipped source file
Every shipped first-party Python source file SHALL begin with a license header declaring
`SPDX-License-Identifier: LicenseRef-CAL-0.2` and a copyright line. This covers files under
`kaine/`, `scripts/`, `tests/`, and the repository top level. Vendored third-party code under
`external/` is exempt and
SHALL retain its upstream headers. The header SHALL be applied by an idempotent script (re-runnable
as files are added) and SHALL sit above the module docstring, after any shebang line.

#### Scenario: Shipped file carries the header
- **WHEN** any first-party `.py` under `kaine/`, `scripts/`, `tests/`, or the top level is inspected
- **THEN** its first non-shebang lines declare `SPDX-License-Identifier: LicenseRef-CAL-0.2` and a
  copyright line

#### Scenario: Vendored code is exempt
- **WHEN** a file under `external/` is inspected
- **THEN** it is not required to carry the CAL header and retains its upstream license header

#### Scenario: Re-applying is a no-op
- **WHEN** the header-application script is run a second time
- **THEN** no file is modified (headers are not duplicated)

### Requirement: NOTICE and contributor terms
The repository SHALL include a root `NOTICE` file recording the CAL reference and status, the
copyright, the reference to the Intrinsic Values required by CAL Article 6.1, and third-party
attributions. `docs/contributing.md` SHALL state that inbound contributions are licensed under CAL
and are subject to the Article 4 entity-welfare obligations.

#### Scenario: NOTICE present
- **WHEN** the repository root is inspected
- **THEN** a `NOTICE` file exists referencing CAL, the copyright, the Intrinsic Values, and
  third-party attributions

#### Scenario: Contributor terms stated
- **WHEN** `docs/contributing.md` is read
- **THEN** it states that contributions are licensed under CAL and subject to the welfare obligations

### Requirement: Header presence is enforced by the test suite
The test suite SHALL include a check that fails if any shipped first-party `.py` lacks the SPDX
header, so the header set cannot silently rot.

#### Scenario: Missing header fails the suite
- **WHEN** a shipped first-party `.py` is added without the SPDX header
- **THEN** the license-header test fails, naming the offending file

