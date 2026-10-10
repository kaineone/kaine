## ADDED Requirements

### Requirement: Documentation follows the paper and the code of record

The documentation SHALL describe the design as the paper of record states it
and the implementation as the code does, and SHALL say which parts of the
paper's planned test are not yet built. Where a page and the code disagree on
a fact about the implementation, the page SHALL be corrected; where the code
and the paper disagree, the page SHALL describe the code and the disagreement
SHALL be tracked as a code change.

#### Scenario: Configuration tables match the shipped file

- **WHEN** a reader looks up a key in the configuration appendix
- **THEN** its type and default match `config/kaine.toml` or, for keys absent
  from that file, the default in code

#### Scenario: Unbuilt parts of the planned test are marked

- **WHEN** a page describes the planned test of workspace mediation
- **THEN** it states that the matched and pooled arms, the positive control
  and the calibration are not yet built
