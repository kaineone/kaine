## ADDED Requirements

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
