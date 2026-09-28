## 1. Nous

- [ ] 1.1 `nous.proposal` in place of `intent.act` on `nous.out`, with preference-scaled salience. `no_op` publishes nothing. The false Soma/maintenance comment is corrected.
- [ ] 1.2 Taken-action feedback: consume `volition.proposal_outcome` from `volition.feedback`; `record_taken_action` before each step; late outcomes counted.

## 2. Volition

- [ ] 2.1 `NousProposalSource` wrapping the configured policy: conscious-proposal realization under the shared guards, `origin: "nous"`, the `rest` kind, and outcome events on `volition.feedback` for every proposal seen (including on inhibited snapshots). `volition.feedback` is added to the stream registry.
- [ ] 2.2 `[nous].drive_actions` (default true) wiring in `kaine/cycle/__main__.py`; run identity records it.

## 3. Realization and audit

- [ ] 3.1 Hypnos honours `intent.rest` with `requested_rest_min_interval_s`, and publishes `hypnos.rest_request`. Lingua ignores `rest`.
- [ ] 3.2 Ignition audit `nous_initiated` category and proposal counts; taxonomy; FaithfulRenderer template.

## 4. Verification and docs

- [ ] 4.1 Tests:
  - an inhibited coalition never realizes a proposal;
  - a non-conscious proposal is never realized;
  - the guards and the superseding rule;
  - `drive_actions = false`;
  - the learning feedback (realized vs declined vs late);
  - the rest rate limit;
  - the audit categories.

  Plus an end-to-end cycle test in which a conscious `think` proposal yields `internal_speech`.
- [ ] 4.2 Docs: the Nous, Volition, Hypnos and Lingua module pages, configuration, and research event streams.
- [ ] 4.3 Offline suite green; `openspec validate nous-drives-action --strict`.
