# Voice-development requirement tightening (2026-11-16)

## Strict validation result

Command:

```bash
openspec validate voice-development --type change --strict
```

Result: invalid under strict, with two warnings and no errors.

| Spec file | Requirement | Requirement text (SHALL-only body) length |
|---|---|---:|
| divergence-assessment/spec.md | Divergence assessment includes the voice-distinctiveness arm | 842 chars |
| sleep/spec.md | Voice alignment trains only on a validated preference source, with collapse defences | 674 chars |

OpenSpec threshold: 500 characters of requirement text. Each warning suggests moving examples and edge cases into scenarios, or splitting the requirement into requirements that each state one behaviour.

No spec files were edited for this note.

## Recommended approach

Prefer splitting rather than shortening prose only. Each resulting requirement should carry its own `#### Scenario:` blocks, and examples or edge cases should move out of the requirement sentence and into those scenarios.

### Divergence assessment arm

Current requirement combines arm membership, measurement definition, default threshold, missing or unreadable evidence, secondary-signal status, signal reporting, and the absence of a consolidation arm.

Tightened split (all proposed bodies are under 500 characters):

1. Voice-distinctiveness is a divergence arm

   The divergence assessment SHALL include a voice-distinctiveness arm alongside the individuation permutation test and self-model drift.

2. Voice distinctiveness marks divergence

   The voice-distinctiveness arm SHALL mark organ-level divergence when the content-free stylometric distinctiveness of the entity's utterances from the base organ crosses its threshold.

3. Uncalibrated distinctiveness defaults to protecting

   Until calibrated, the distinctiveness threshold SHALL be 0, so any entity with at least one measured utterance counts as diverged by this arm.

4. Missing distinctiveness evidence counts as diverged

   Unreadable or missing distinctiveness evidence SHALL count as diverged.

5. Accepted adapter is a secondary signal

   The accepted-adapter boolean SHALL be retained only as a weaker secondary signal.

6. Arm values appear in signals

   The voice-distinctiveness arm's numeric values SHALL appear in the assessment's signals.

7. No consolidation arm

   There SHALL be no consolidation (template-comparison) arm; voice adaptation computes no organ-level divergence until a validated preference source exists (paper section 3.5).

Alternative: keep one requirement and move items 3-7 into scenarios, retaining item 1 as the only requirement sentence. That is less precise but produces fewer delta entries.

### Voice alignment training

Current requirement combines source validation, all five collapse defences, and the no-source reporting rule.

Tightened split (all proposed bodies are under 500 characters):

1. Validated preference source only

   The voice-alignment phase SHALL build training examples only from a preference source that has passed its recorded offline validation.

2. Self-generated preferred data accumulates

   Self-generated preferred text SHALL be drawn only from a corpus that accumulates across sleeps without replacement.

3. Fixed real-data share

   Each training batch SHALL contain a fixed share from a fixed real-data set.

4. Selection by an uncontrolled signal

   Preference selection SHALL be by a signal the generator does not control.

5. Previous accepted adapter as reference

   Training SHALL start from the entity's previous accepted adapter as the reference.

6. Monitors in band

   Diversity and distinctiveness monitors SHALL remain inside the maturation band in both directions.

7. No validated source means no training

   When no validated preference source is configured, the phase SHALL train nothing and report that in the sleep summary.

Alternative: retain one requirement that lists the five defences in a single sentence (405 characters) and move the examples into scenarios. Splitting is preferred because each defence is independently testable and corresponds to one design decision in D3.

## Suggested edit scope

- Target files:
  - openspec/changes/voice-development/specs/divergence-assessment/spec.md
  - openspec/changes/voice-development/specs/sleep/spec.md
- Do not change scenario intent; only redistribute clauses between requirement sentences and #### Scenario: blocks.
- After editing, verify with `openspec validate voice-development --type change --strict`.
