# Spec Delta

## ADDED Requirements

### Requirement: content-in-broadcast
When the content level is active, each non-inhibited broadcast's metadata includes the shared code `z_k` under a `content` key. Modules that read the broadcast may condition on `z_k` in addition to the existing access summary.

#### Scenario: broadcast with content
- **WHEN** the content level is active and a non-inhibited broadcast is published
- **THEN** `broadcast.metadata["content"]` contains `z_k` as a sequence of floats of length `code_dim`

#### Scenario: broadcast without content
- **WHEN** the content level is disabled or the broadcast is inhibited
- **THEN** `broadcast.metadata` does not contain a `content` key

### Requirement: selection-unchanged
The workspace's competitive selection mechanism (intensity, novelty, goal, affect contrast) is unchanged by the content level. The content level encodes the output of selection; it does not influence selection itself.

#### Scenario: selection produces the same coalition with or without content
- **WHEN** the same events arrive at the workspace with the content level on and off
- **THEN** the selected coalition (members, scores, access threshold) is identical
