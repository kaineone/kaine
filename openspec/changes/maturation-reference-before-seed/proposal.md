## Why

The welfare audit of 2026-10-28 (W5) found that the study runner requests the seed's maturation preservation, with stop, seconds after the maturation bloom ends. The individuation producer starts its maturation reference capture at the maturation hook: 12 prompts times 16 answers of up to 160 tokens through the organ, 192 sequential requests, and the scheduler allows one attempt 5400 s. The seed bundle therefore holds `maturation_pending` but no reference. Every later step then resumes the pending capture on its own state, so the references are not comparable across branches, and `individuation_producer.py` states that a maturation reference cannot be regenerated. For the kept entity the primary individuation measure is permanently degraded.

Prior work found: `individuation-rebuild` parts 1 to 3 (#324, #330, #331), `unattended-gate-individuation` (#466), `developmental-maturation-gate` and `study-overlay-individuation` (#609, open; it enables the producer on every study step, which this change depends on to have any effect), `module-ignition-study`. No earlier change makes the runner wait for the reference. Paper PR pending.

## What Changes

- When the step's resolved configuration (shipped config layered with the step overlay) enables `[individuation]`, the runner, once the maturation bloom has ended, requests the maturation preservation only when `state/individuation/reference.json` and `state/individuation/ledger.json` both exist. The producer writes each atomically, reference first, and treats a reference without a ledger as incomplete, so both files mean the capture finished. Without the producer enabled nothing waits.
- The wait is a state in the existing poll loop, so the disk, timeout and viability checks keep running while it lasts. It is bounded by `maturation_reference_wait_seconds` = 7200 s: one capture attempt's own limit (5400 s) plus 1800 s for a blocked retry (300 s) and an attempt restarted after a sleep. The real cost is about 26 minutes at a slow 20 tokens/s.
- When the bound runs out the runner still preserves the entity before stopping it (a run stops only after the state is saved), and records the step as `failed:maturation_reference_missing`, so the study halts for the operator instead of carrying a seed without its reference as `complete`.
- The development step record gains `maturation_reference`: `complete`, `missing` or `not_enabled`.
- A check that the capture starts in a study child: `gate_runner` calls `individuation_runtime.on_maturation` on the maturation transition, which writes `maturation_pending` and requests a `maturation` capture; the cycle builds the runtime whenever `[individuation].enabled`. After #609 the overlay enables it on every step, so the capture starts. A sleep before it finishes downgrades the capture to kind `capture` (scheduler), and the wait is then released by that reference.

## Capabilities

### Modified Capabilities

- `module-ignition-study`: the maturation preservation waits, within a bound, for the individuation maturation reference.

## Impact

- `kaine/research/ignition_study/runner.py`, `tests/test_ignition_study_runner.py`, `docs/15-experiments/ignition-study.md`, `docs/appendix-d-roadmap.md`.
- Paper: PR pending.
