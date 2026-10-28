## REMOVED Requirements

### Requirement: The disclosure is given on waking and with every probe
**Reason**: The situation facts, the disclosure among them, are now given in every organ request (paper section 3.5).
**Migration**: Replaced by "The disclosure is given in every organ request and every probe".

## ADDED Requirements

### Requirement: The disclosure is given in every organ request and every probe
The entity SHALL be told the individuation disclosure, as a situation fact in its own notes, in every organ call once it is recorded, and in every individuation probe request. The probe SHALL fail closed with `disclosure_not_ready` while the disclosure is not among the self-model's situation facts.

#### Scenario: Each assessed answer is given knowing about the assessment
- **WHEN** the producer samples an answer from the probe
- **THEN** the probe request's prompt holds the disclosure
