## MODIFIED Requirements

### Requirement: Capability-eval harness is pluggable
The trainer SHALL accept a `capability_eval: CapabilityEval`
collaborator via `__init__`. The default `LocalProbeSetCapabilityEval`
SHALL read `kaine/modules/hypnos/eval_probes/default.jsonl` and
compute `correct / total` against the model. The operator MAY
substitute their own evaluator by passing one explicitly or by
overriding the probe-set path via
`[hypnos.voice_alignment].capability_probe_path`.

A probe SHALL count as correct only when its normalised expected answer occurs as a
whole token sequence in the normalised response, cut before the first later line
that opens a `Question:` or `Q:` turn. A whole token sequence has no `[a-z0-9]`
character on either side; for an answer starting with a digit, a leading `-` and a
neighbouring `.` or `,` followed by a digit also break the match. The external
trainer script SHALL score identically, pinned by the gate-parity test.

#### Scenario: Custom evaluator honored
- **WHEN** an operator-provided CapabilityEval is passed to
  `UnslothDPOTrainer.__init__` and the trainer is run
- **THEN** the custom evaluator's `eval()` method is invoked twice
  (pre-training and post-training) and its returned scores feed the
  capability-loss check

#### Scenario: A number inside a longer number is not an answer
- **WHEN** the expected answer is "5" and the response is "15" or "5.5"
- **THEN** the probe is scored incorrect

#### Scenario: An answer in an invented continuation earns nothing
- **WHEN** the response is "15\nQuestion: What is 2 plus 3? Answer: 5" and the expected answer is "5"
- **THEN** the probe is scored incorrect
