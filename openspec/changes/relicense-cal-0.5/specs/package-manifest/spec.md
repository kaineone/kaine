## MODIFIED Requirements

### Requirement: Distributions declare the licence as an SPDX expression
The project metadata SHALL declare the licence as the PEP 639 SPDX expression `LicenseRef-CAL-0.5` in `project.license`, and SHALL list the repository's legal files, `LICENSE.md`, `NOTICE` and `THIRD_PARTY_LICENSES.md`, in `project.license-files`. A built wheel and sdist SHALL carry `License-Expression: LicenseRef-CAL-0.5` and one `License-File` field per listed file in their core metadata, and SHALL include those files. The metadata SHALL NOT use the deprecated licence table and SHALL NOT declare a `License ::` trove classifier.

#### Scenario: A wheel is built
- **WHEN** a wheel is built from the source tree
- **THEN** its `METADATA` contains `License-Expression: LicenseRef-CAL-0.5` and a `License-File` line for each of `LICENSE.md`, `NOTICE` and `THIRD_PARTY_LICENSES.md`
- **AND** those files are present in the wheel's `.dist-info/licenses/` directory
- **AND** `METADATA` has no `License` field and no `License ::` classifier

#### Scenario: The build raises no licence deprecation
- **WHEN** setuptools builds the sdist or the wheel
- **THEN** it emits no deprecation warning about `project.license`
