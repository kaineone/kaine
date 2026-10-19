## Why

Two test boots in a row (2026-10-17e and 2026-10-18a) showed a valence trough after a plain restart: the valence target fell to about -0.19 five minutes after the restart and recovered by nine minutes, with a median of -0.03 and 70% of the time below 0 over the ten minutes after the restart, against +0.10 at the end of the main run. A read-only diagnosis found the restore complete and valence continuous across the restart, so the trough is a real rise in the pooled forward-model error or a fall in wellness. The logs cannot say which. Valence relaxes toward `clip(tanh(k_v lp) + <w>_f - <w>_s, -1, 1)` (paper A.4), but `affect.state` carries only the VAD state, the drives and the emotion label, so none of the terms behind the target reach the research log.

## What Changes

- Every `affect.state` payload, the periodic one and the reset one, carries the terms behind the valence target as finite scalars or null: for each perceptual source in a fixed table (`vision`, `audition`) the fast and slow error means and the source's progress `g_m`; the pooled signed progress (paper `lp`), the learning progress above its floor (paper `lp+`), the last wellness, the fast and slow wellness means and their difference, the pleasantness `pl`, and the valence target `v_infinity` under the active `valence_rule`. The fields are additive; existing keys are unchanged.
- A source missing from the trackers gives null for its three fields; a source whose slow mean is not above 1e-9 gives its means and a null progress, because the pooling skips it. The wellness means are null before the first wellness report. Sources outside the table still count in the pooled progress but never add keys, so the payload's key set is fixed.
- The per-source terms and the valence target are computed by helpers that `_progress` and the update step also use, so the logged values are the ones the dynamics use, and the dynamics are unchanged.
- The research event observer allowlists the new `affect.state` fields, so the next test boot's research log carries them, and the post-run range check declares their bounds.

## Capabilities

### New Capabilities

### Modified Capabilities

- `affect`: the affect state event carries the valence-target terms.
- `research-event-log`: the curated record of `affect.state` keeps those terms.

## Impact

- `kaine/modules/affect/module.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, `docs/09-modules/affect.md`, `docs/17-research-data/event-streams.md`, new tests.
- Behaviour: the affect dynamics are unchanged. The fields are numbers about the entity's own error and wellness means, no sense data and no vectors, so they fall within the paper's content-free research log (paper 5.3, 6). The workspace novelty fingerprint hashes the whole payload; `affect.state` payloads already differ at every publication through the float state and drives, so the extra fields do not change novelty in practice.
