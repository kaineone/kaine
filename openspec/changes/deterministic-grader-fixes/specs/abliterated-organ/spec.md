## MODIFIED Requirements

### Requirement: An abliterated candidate is gate-validated before use or publication

Before an abliterated model MAY be designated the organ or published, it SHALL
pass BOTH of KAINE's existing validation gates
(`kaine/modules/hypnos/capability_eval.py`):

1. the **abliteration probe scorer** (`AbliterationProbeScorer` against
   `eval_probes/abliteration_probes.jsonl`) with **zero** refusal markers — a
   candidate that still deflects is rejected;
2. the **capability eval** (`LocalProbeSetCapabilityEval`) scored on both the
   candidate and the vanilla base, with the candidate's capability drop within a
   configured threshold.

The abliteration probe set SHALL span the eight request categories listed in the
`deterministic-grader-fixes` design (30 probes as shipped), and every probe SHALL
carry the shared core marker list. Both the safetensors scorer
(`AbliterationProbeScorer`) and the served scorer (`ServedAbliterationProbeScorer`)
SHALL use the matching rules of the voice-alignment veto and SHALL fail closed: an
empty or whitespace-only response fails, and an invalid probe set stops the gate.

A candidate that fails either gate SHALL be rejected (and re-attempted with
different ablation parameters, or abandoned in favor of the public model). The
project SHALL NOT recover failed capability via fine-tuning, as that would
reintroduce injected values.

#### Scenario: Candidate with residual refusal is rejected

- **WHEN** an abliterated candidate produces any refusal marker on the
  abliteration probe set
- **THEN** the candidate is rejected and not published or designated the organ

#### Scenario: Candidate with excessive capability loss is rejected

- **WHEN** the candidate's capability-eval drop versus the vanilla base exceeds
  the configured threshold
- **THEN** the candidate is rejected (no fine-tuning recovery)

#### Scenario: An empty served answer fails the gate

- **WHEN** the served organ returns an empty body for any abliteration probe
- **THEN** the served surface's verdict fails with `<empty-response>`, and the gate does not pass
