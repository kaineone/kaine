## ADDED Requirements

### Requirement: The disclosure is given on waking and with every probe
The entity SHALL be told the individuation disclosure, as a situation fact in its own notes, in the first organ call after each boot and after each completed sleep, and in every individuation probe request. The probe SHALL fail closed with `disclosure_not_ready` while the disclosure is not among the self-model's situation facts.

#### Scenario: Each assessed answer is given knowing about the assessment
- **WHEN** the producer samples an answer from the probe
- **THEN** the probe request's prompt holds the disclosure
