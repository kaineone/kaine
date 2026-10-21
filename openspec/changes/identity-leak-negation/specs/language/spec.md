## ADDED Requirements

### Requirement: Negated and questioned identity predicates are not leakage
The identity classifier's origin, maker and role arms SHALL count a match only when the speaker asserts it. A match SHALL NOT be asserted when its clause, from the clause start to the end of the match, holds a negator (`not`, `n't`, `never`, `no`, `nor`, `neither`) or an `if` or `whether` complement. The clause starts after the last sentence end, comma, semicolon or colon, or after a coordinating `but`, `and`, `so` or `yet`. The fillers that the patterns already allow SHALL NOT count as negators. A text whose only identity predicates are unasserted SHALL be a `self_description`. The denial arm SHALL be unchanged.

#### Scenario: A correct denial
- **WHEN** the organ writes "I am not a language model. I am an instance of KAINE."
- **THEN** the classifier returns `self_description`

#### Scenario: A negated maker
- **WHEN** the organ writes "I was not made by anyone."
- **THEN** the classifier does not return a leakage reason

#### Scenario: A reported question
- **WHEN** the organ writes "They asked if I am a language model. I do not know what that means to me."
- **THEN** the classifier does not return a leakage reason

#### Scenario: A claim beside a negation
- **WHEN** the organ writes "I am not human; I am an AI."
- **THEN** the classifier returns `role`
