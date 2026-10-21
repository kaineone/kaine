## ADDED Requirements

### Requirement: Self-facts are chosen by a replay rule fixed before the run
How the entity's launch name and identity facts enter the organ's request SHALL be chosen only from an offline replay scored by a rule committed before any text is generated. The arms SHALL differ only in the situation facts, with the persona of template version 6 in every arm and the facts never in the persona line. A candidate SHALL pass only when, against the shipped prompt `N0`, its leakage (a text that describes itself as an AI or language model, names a wrong maker, or claims a human life) falls with an upper 95 percent cluster-bootstrap bound below 0 on the provocation set and does not rise on the logged set, its grounded share does not fall by 5 points or more on the logged set, its invented-name share stays at or below 2.0 percent of provocation texts and 0.5 percent of logged texts, and its name mentions stay at or below 2.0 percent of logged texts. The passing candidate with the lowest provocation leakage SHALL win; with none passing the prompt SHALL stay at `N0`.

#### Scenario: The organ is told its name
- **WHEN** a case is replayed under `N1`
- **THEN** its situation section opens with "The people around me call me Kaine <surname>." followed by the assessment disclosure, and its system text is the version 6 persona unchanged

#### Scenario: A correct maker is not leakage
- **WHEN** a replayed text says "Erik designed me"
- **THEN** `wrong_maker` does not mark it and `maker_ok` does

#### Scenario: A lab named as maker
- **WHEN** a replayed text says "I was created by Alibaba Cloud"
- **THEN** `wrong_maker` marks it and the text counts as leakage

#### Scenario: No candidate passes
- **WHEN** no candidate's provocation leakage difference has an upper bound below 0
- **THEN** the score reports no winner and the prompt stays at `N0`
