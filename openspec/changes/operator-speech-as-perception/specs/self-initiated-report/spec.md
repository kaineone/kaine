## MODIFIED Requirements

### Requirement: Self-initiated, not input-triggered

The policy SHALL form intents from the entity's OWN workspace state, the precision-weighted scores of the accessed coalition, and SHALL NOT depend on any user utterance or transcription event. A heard transcription in the coalition SHALL be treated as any other member: it MAY lead to a report when it is the coalition's top member and the bars and guards allow, and the policy SHALL NOT test any member's source, type or channel except to leave the language module's own output aside. It never answers input by rule; it reports its own state, heard speech included.

#### Scenario: No utterance is needed to speak

- **WHEN** the coalition contains only the entity's own predictive signals (no
  user-utterance / transcription event) and crosses the report threshold
- **THEN** the policy still forms a `speak` intent (report is self-initiated)

#### Scenario: Inhibited snapshot yields nothing

- **WHEN** the snapshot is inhibited (no coalition crossed the conscious threshold)
- **THEN** the policy forms no intent

#### Scenario: A heard utterance that leads the coalition

- **WHEN** an accessed operator transcription is the coalition's top member, its score clears the speak bar, and no guard, refractory or signature block applies
- **THEN** the policy forms a `speak` intent whose `about` names the event in felt or numeric words, with no word of the transcription

#### Scenario: A heard utterance below the bar

- **WHEN** an accessed operator transcription is the coalition's top member and its score is below the think bar
- **THEN** the policy forms no intent
