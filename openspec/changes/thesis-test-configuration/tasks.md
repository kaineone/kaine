## 1. Self-initiated report policy

- [x] 1.1 Add `kaine/workspace/report_policy.py::SelfInitiatedReportPolicy`
  (ActionSelectionPolicy): inhibition gate first; compute precision-weighted
  surprise = max selected `salience_scores`; two-tier `think_threshold` <=
  `report_threshold` (both > publication threshold); novelty (last-report content
  signature) + refractory intervals + one-in-flight guards for speak and think;
  self-initiated only (never reads utterance/transcription events).
- [x] 1.2 Tests (spec `self-initiated-report`): conscious-but-not-reportworthy is
  silent; high surprise reports once; self-initiated with no utterance present;
  inhibited yields nothing; refractory + one-in-flight suppress; repeated content
  not re-reported; moderate surprise thinks-not-speaks.

## 2. Audition transcription gate (STT-ectomy)

- [x] 2.1 Add `[audition].transcription_enabled` (default true); when false, skip
  the STT call and the `audition.transcription` publish, leaving `audition.
  perception`/emotion/prosody untouched. STT code preserved.
- [x] 2.2 Tests (spec `audition-predictive`): disabled → no transcription event, no
  STT invoked; perception path still publishes; default (enabled) unchanged.

## 3. Volition policy selection

- [x] 3.1 Wire `[volition].policy` in `kaine/cycle/__main__.py` to select
  `self_initiated_report` (the new policy) alongside the existing default/drive
  policies; default selection unchanged.

## 4. Thesis-test profile

- [x] 4.1 Add `config/profiles/thesis_test.toml`: enable soma/chronos/topos/
  audition/lingua; disable the rest; `[audition].transcription_enabled=false`;
  Topos foveation on; perception feed raw AV; `[volition].policy=self_initiated_report`.
- [ ] 4.2 Test: booting the profile registers exactly the five modules, hits no
  disabled-module dependency, and selects the report policy.

## 5. Paper reconciliation (review-gated, not committed by this change)

- [ ] 5.1 Update the paper's minimal-set (§1.4/§3.4), audio-input (§2.4/§4), and
  action/report framing to the base-thesis form; keep it non-technical. (A
  paper-agent prompt accompanies this change.)

## 6. Verification

- [x] 6.1 Run the suite + `lint-imports`; confirm no default behavior changed and
  the shipped-config all-off guard still passes.
- [x] 6.2 Confirm the offline workspace-mediation ablation still runs (the
  falsification instrument), now applicable to the richer processor set.
