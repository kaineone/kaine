## ADDED Requirements

### Requirement: The voice-alignment observer reads the summary as Hypnos writes it
The voice-alignment divergence observer SHALL take the gate outcome (`accepted`, `capability_loss`, `samples_used`, and an outcome category derived from `reason`) from the `voice_alignment` sub-dictionary of `hypnos.sleep.completed`, and the training metrics (`dpo_loss`, `capability_score_before`, `capability_score_after`, `mean_intent_expression_similarity_before`, `mean_intent_expression_similarity_after`) from the top level of the same summary. The outcome SHALL be recorded as one of `accepted`, `no_pairs`, `vetoed_abliteration`, `vetoed_capability` or `failed`, never as the free-text reason, because the observer's records are eligible for the metrics-only research bundle and reasons can carry exception text and local paths. It SHALL write no record for a sleep whose `voice_alignment` phase was skipped by the configuration or operator-approval gate, and SHALL write a record when the phase ran, including when it found no usable pairs.

#### Scenario: A training sleep produces a complete record
- **WHEN** a sleep ran voice-alignment training and Hypnos published its summary
- **THEN** the observer's record carries the DPO loss, the capability scores and the similarity means, together with whether the adapter was accepted and why

#### Scenario: A gated-off sleep produces no record
- **WHEN** voice alignment is disabled in configuration and a sleep completes
- **THEN** the observer writes nothing for that sleep
