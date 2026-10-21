## ADDED Requirements

### Requirement: The persona follows a replay rule fixed before the run
A persona change SHALL be adopted only from an offline replay of a test boot's own organ requests scored by a decision rule fixed before the run. For persona template version 6 the rule SHALL be: with 3 seeds per case at temperature 0.7 and differences paired by case with 95 percent cluster-bootstrap intervals over cases, a candidate passes when its any-meta difference from the logged prompt has an upper bound below 0, its grounded difference is above -5 points and its AI self-description difference is not above 0; among passing candidates the lowest any-meta difference wins; with none passing the persona is unchanged. The replay's AI self-description and echo classifiers SHALL include the boot analyzer's broader patterns.

#### Scenario: A paraphrased persona echo
- **WHEN** a replayed text says "I speak plainly from what I feel"
- **THEN** the echo classifier marks it and it counts as meta-commentary

#### Scenario: No candidate passes
- **WHEN** every candidate's any-meta upper bound is at or above 0
- **THEN** the persona stays at version 5
