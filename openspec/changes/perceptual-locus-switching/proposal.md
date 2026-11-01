## Why

The perceptual locus exists, and it is held for two reasons stated on its page (`docs/09-modules/perceptual-locus.md`, "Status"): no module produces `intent.perceptual_locus.switch`, and there is only one source. `perceptual-sources` provides several sources: the programme, a USB webcam with a microphone, and a MuJoCo simulated world. This change makes the locus real. The entity may choose among the registered sources by its own action selection, from its own drives, with nothing hardwired about which source relieves what. The operator can always override. A switch is treated as what the research says it is to a brain: a large, self-caused prediction-error event, followed by adaptation that should show savings on return (`kaine-research/sensors-bodies-locus-research-2026-11-01.md`, section 8).

### What already exists (audit, origin/main d7fabdc0)

- **The locus.**
  - The locus classes are `physical`, `virtual` and `off`, with physical XOR virtual as the privacy invariant (`kaine/perception_state.py:42-49`).
  - A gate function checks a self-switch in this order: valid, a real change, lock (operator or development), policy, inhibition, dwell on entity time (`perception_state.py:303-335`).
  - The applier module consumes `intent.perceptual_locus.switch` from the action-selection stream (`kaine/modules/perceptual_locus/module.py:95-136`).
- **Nothing produces that intent.** Action selection emits only `intent.speak`, `intent.think`, `intent.act` and `intent.rest` (`kaine/workspace/action_selection.py:42-61`).
- **Signed act intents.** `act` intents carry a provenance signature (`action_selection.py:412-421`), and the effectors module realises them only for whitelisted effectors and audits every attempt (spec `effectors`).
- **The drive-led route this change copies.** The stimulus-control act (branch `build/stimulus-control`, change `stimulus-control-act`, not yet merged) shows the pattern:
  - **Stage M.** After maturation, a broadcast led by the entity's own boredom or restlessness drive event yields one signed act whose action is drawn uniformly, with a run-seeded generator (`kaine/workspace/stimulus_policy.py` on that branch).
  - **Credit window.** Within the window after the act, novelty or learning progress counts as the entity's own response for boredom.
  - **Bounds and records.** Bounds, a refusal reported as a failed act, a content-free record, and off equal to absent.
- **Sleep and locus.** Sleep sets the locus to `off` and restores the pre-sleep locus (spec `perception-feed`, "Perceptual locus restore after sleep").
- **Developmental lock.** The developmental phase locks the locus to `virtual` with `locked_by = "development"` (`kaine/cycle/__main__.py:2005`; released at maturation, `kaine/lifecycle/gate_runner.py:690`).
- **Prediction-error normalisation.** Vision normalises its prediction error by a rolling mean over 32 reports and alerts at twice that mean (`kaine/modules/vision/module.py:668-673`, `705`). It has one forward model for every world it sees (`module.py:221`, `329-336`).

### What is wrong or missing

- **No producer of a switch.** The locus selects a class, not a source.
- **A field mismatch with the research log.**
  - The locus events publish `{locus, by}` and `{requested, reason}` (`perceptual_locus/module.py:124-131`).
  - The research-event allowlist expects `{locus, changed_by}` and `{locus_requested, denied_by, reason_label}` (`kaine/evaluation/observers/research_event_observer.py:467-468`).
  - So the research log keeps only the locus of a change and nothing of a denial: a producer/consumer event-contract bug.
- **The self-model is not updated.** The `perceptual-locus` spec says a self-switch is "reflected in the self-model module's embodiment self-image". The self-model module has no such field: no reference to embodiment or the locus in `kaine/modules/self_model/`.
- **One forward model per processor, shared by every world.**
  - A switch trains that model on the new world and overwrites what it learned of the old one.
  - That is the interference case of the motor-adaptation literature (Krakauer, Ghez and Ghilardi 2005, *J Neurosci* 25:473-478).
  - The context-specific alternative is MOSAIC (Wolpert and Kawato 1998, *Neural Netw* 11:1317-1329; Haruno, Wolpert and Kawato 2001, *Neural Comput* 13:2201-2220).
- **A fixed drive claim.** `PerceptualLocus.relieves_drives = {"curiosity", "boredom"}` (`module.py:43`) is a fixed claim of what switching relieves. This change does not depend on it. Its replacement by learned valuation belongs to `learned-action-selection`.

## What Changes

1. **The locus selects a source.**
   - Desired state gains `source`, written only when the registry is on.
   - The locus class follows the selected source's declared class, so physical XOR virtual holds unchanged.
   - The operator selects a source through a new dashboard route, behind the operator token. The existing `/locus` route keeps working: `off` as today, and `physical` or `virtual` select that class's configured default source.
2. **The entity's act.**
   - A `perceptual_source` effector, in process, built only when self-switching is on and run only when the operator's whitelist names it.
   - It realises a signed act intent whose parameter is the target source id.
   - It hands the request to one arbiter, shared with the `PerceptualLocus` module, which keeps consuming the legacy intent type through the same arbiter.
3. **Gates, in order:**
   - a registered source;
   - available;
   - entity-selectable;
   - a real change;
   - not locked (operator or development);
   - policy (`allow_self_switch`);
   - not inhibited;
   - not asleep;
   - mature;
   - not under a welfare hold;
   - minimum dwell, longer for a source the entity has never been in;
   - a cap on switches per awake hour.

   A refused switch changes nothing, is reported as a failed act (so the entity perceives that its act did not take), and is audited with a closed reason label.
4. **Stage M.**
   - After maturation, a non-inhibited broadcast led by the entity's own boredom or restlessness drive event yields one signed switch act once the dwell allows.
   - The target is drawn uniformly, with a run-seeded generator, from the sources the arbiter would accept now.
   - When the stimulus-control stage M is also installed, one composed source draws once from the union of both act sets, so a broadcast yields at most one act on the entity's input, and neither act is privileged.
   - Stage L (learned choice through `act-intent-derivation` and `learned-action-selection`) follows those changes.
5. **Credit.** Novelty or learning progress within the response window after the entity's own realised switch counts as its own response for boredom. This extends the stimulus-control credit window to the switch effector.
6. **Per-source forward-model contexts.**
   - The vision and audition processors keep a bank of contexts keyed by source id. Each context holds the forward model, the rolling prediction-error window, and the change and habituation baselines.
   - On a switch the processor binds the selected source's context.
   - A never-seen source starts from a copy of the current context. A copy keeps what transfers, as forks start from a copy of their parent.
   - Returning to a known source finds its context intact, which gives savings and no interference.
   - The bank is persisted as the single model is today: weights and statistical summaries only.
   - Selection by prediction error among contexts (MOSAIC's online correction) is stage 2. It is needed when a source's world changes underneath its label.
7. **The switch transient is kept and bounded.**
   - The prediction-error burst on a switch is the brain's own "the world changed" signal (Garrido et al. 2009, *Clin Neurophysiol* 120:453-463), and it competes for access like any surprise.
   - It is bounded by the new context's own baseline, by the dwell and the hourly cap, by the maturation and sleep gates, and by a welfare hold. The hold suspends entity switching after two of the last three switches were followed by a welfare gray-zone event or a protective action, and the operator lifts it.
   - The switch event is the efference copy. Processors use it to bind the context, the cue of MOSAIC. Attenuating a self-caused transient (Blakemore, Wolpert and Frith 2000, *Neuroreport* 11:R11-R16) is not built until the readout shows it is needed.
8. **The self-model's embodiment record.** The self-model keeps a label-only record of the three components Blanke separates (2012, *Nat Rev Neurosci* 13:556-571): self-location (the source id), body (the paired body or none) and perspective (the camera name). No content.
9. **The event contract is fixed.**
   - `perceptual_locus.changed` carries `locus`, `source` and `changed_by`.
   - `perceptual_locus.denied` carries `locus_requested`, `source_requested`, `denied_by` and `reason_label`.
   - The research allowlist matches both.
10. **The readout.** A per-viewing `perceptual_switching` welfare record:
    - switches by target and by initiator;
    - refusals by reason;
    - dwell times, and the share of awake time away from the programme;
    - per switch: each processor's normalised error before and after, alerts in the minute after, the adaptation time (the time to return within 1.5 times the new context's baseline), whether the context was new or revisited, and the arousal peak;
    - boredom after the entity's own switches compared with otherwise.

    It holds numbers and labels only.
11. **Off equals absent.** With self-switching off, nothing of the act, the stage-M source, the credit window or the welfare hold is built. With the registry off, nothing of this change is built. Each is checked against a golden digest.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `perceptual-locus`: selection of a registered source, the operator source route, the switch effector and arbiter with its gates, the welfare hold, the event fields, the self-model record.
- `action-selection`: the stage-M switch act and its composition with the stimulus-control act.
- `perception-feed`: sleep restores the pre-sleep source.
- `vision-predictive`: forward-model contexts per source (audition follows the same requirement through `audition-predictive`, written at implementation).
- `evaluation-observers`: the `perceptual_switching` record, the allowlist fix, and the off-equals-absent checks.

## Impact

- **Code.**
  - `kaine/perception_state.py`: `source` in desired state, and the gates.
  - `kaine/modules/perceptual_locus/module.py`: the arbiter, event fields.
  - A new `kaine/modules/effectors/perceptual_source.py`.
  - `kaine/workspace/stimulus_policy.py`, or a new `kaine/workspace/input_act_policy.py` that composes both stage-M sources.
  - `kaine/modules/affect/module.py`: credit for the switch effector.
  - `kaine/modules/vision/module.py` and `kaine/modules/audition/module.py`: the context bank.
  - `kaine/modules/self_model/`: the embodiment record.
  - `kaine/modules/sleep/module.py`: source restore.
  - `kaine/dashboard/perception.py`: the source route.
  - `kaine/evaluation/observers/research_event_observer.py` and the welfare observer.
  - `config/kaine.toml`: `[perception]` gains `max_switches_per_awake_hour`, `min_dwell_new_source_s` and the welfare-hold window.
- **Docs.**
  - `docs/09-modules/perceptual-locus.md`, which also gets a rename of its stale `[perception]` wording.
  - `docs/09-modules/effectors.md`, `affect.md`, `self-model.md`, `vision.md`, `audition.md`.
  - `docs/17-research-data/README.md`.
- **Paper.** Via the revision notes: §3.5 and §3.6 (the entity's choice of source), A.4 (credit), A.6 (the composed stage-M rule), and Table A1 (dwell, new-source dwell, hourly cap, welfare-hold window).

## Dependencies and start condition

- **Depends on:**
  - `perceptual-sources`, for the registry;
  - `stimulus-control-act`, merged, for the composed stage-M source and the credit window it extends;
  - `effector-confinement` (branch `spec/grounding-social-safety-2026-10-31`), merged, before the effectors module is enabled at all. The switch effector is in-process and declares a profile with no host side effects.
- **Stage L** depends on `act-intent-derivation` and `learned-action-selection`.
- **Joining an entity.** Turning it on for a running entity is a development-run component join: a two-layer opt-in, its second-review record, and the operator whitelisting the effector. Never inside a running study.
