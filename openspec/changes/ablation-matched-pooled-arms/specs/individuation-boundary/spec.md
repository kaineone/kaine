## ADDED Requirements

### Requirement: The probe decodes at its own fixed temperature
The individuation probe SHALL decode at `[individuation].probe_temperature` (default 0.0, a finite number at least 0), never at the voice's `[lingua].temperature`. Language's probe request SHALL use it, and its probe conditions SHALL report it under the `temperature` key, so a reference captured before this change still matches and a study or voice setting cannot change the probe's conditions.

#### Scenario: The voice temperature does not reach the probe
- **WHEN** Language's voice temperature is 0.7 and the probe temperature is the default
- **THEN** a probe request has temperature 0.0, and the probe conditions equal those of a Language whose voice temperature is 0.0

#### Scenario: A negative probe temperature is refused
- **WHEN** `[individuation].probe_temperature` is -1
- **THEN** loading the individuation configuration raises `ValueError`
