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

The second half of this list was revised after the adversarial review (`kaine-research/paper-audit-2026-10-31/SENSORS-LOCUS-SPEC-REVIEW.md`), with the PM's decisions.

1. **One source of truth.**
   - Desired state persists `source` and a set of off-holders (sleep, freeze, operator), written only when the registry is on.
   - The locus is computed on read from the source's kind-derived class, so physical XOR virtual holds by construction.
   - Every writer (the arbiter, sleep, the developmental lock, the operator routes, the loss fallback) goes through one path with a cross-process `fcntl` lock.
   - The developmental lock pins the programme.
   - Sleep adds and removes a holder.
   - Failed reads resolve to the programme.
2. **The operator.**
   - A new source route, behind the operator token.
   - The `/locus` route keeps working: `off` sets an operator off-holder, and `physical` or `virtual` select the class's configured default source.
3. **The entity's act, conforming to `effector-confinement`.**
   - A `perceptual_source` effector, run only when the operator's whitelist names it. Its confined executor has no network or bus credential, and its only side effect is returning a signed request over its pipe. The effectors module publishes the request verbatim, and the arbiter accepts each request once, within a short window.
   - The arbiter in the cycle verifies the request against the signed act and applies it.
   - The arbiter reads inhibition from the broadcast itself and starts inhibited.
   - With the registry on, the legacy unsigned intent is refused.
4. **Gates, in order:**
   - registered;
   - entity-selectable, with the room approval (checked before availability, so a refusal never reveals a source the entity may not use);
   - available;
   - a real change;
   - not locked;
   - policy;
   - not inhibited;
   - no off-holder;
   - mature;
   - the welfare hold;
   - dwell (120 s on a first visit, a provisional value);
   - a cap of 12 switches per awake hour.

   A return to the programme is exempt from dwell and the cap. A refused switch changes nothing, is reported as a failed act, and is audited with a closed reason label.
5. **The welfare hold never traps the entity.**
   - After two of the last three entity switches were followed by distress, the hold forbids switches into any source but the programme. It never forbids a return.
   - Recurring distress during a hold returns the entity to the programme through the operator path.
   - In unattended runs the advisory escalates through the existing welfare path.
6. **Stage M.**
   - After maturation, a broadcast led by the entity's own boredom or restlessness drive event yields one signed switch act once the arbiter would accept one. The target is drawn uniformly, run-seeded.
   - Composed with the stimulus-control stage M, it is one draw over the union of both act sets, and at most one act per broadcast.
   - Stage L follows `act-intent-derivation` and `learned-action-selection`.
7. **Credit without self-reward.**
   - Within the response window after the entity's own switch, only learning progress counts as its own response for boredom. Alert excess is excluded inside the adaptation period.
   - An offline habituation check, by the stimulus-control method, comes before enabling.
8. **Per-source forward-model contexts, as a declared weight group.**
   - Vision and audition keep a bank keyed by source id, serialised under `forward_model_bank` and declared in `MODULE_WEIGHT_GROUPS` (#638). A merge takes the whole bank from one parent or refuses.
   - A first entry copies weights only, from `state_dict()`: no buffers or latents of the previous world, which may be the room.
   - It starts with empty windows, so a new source's precision is low until its noise is estimated.
   - A return binds the stored context: savings, no interference (MOSAIC).
9. **The switch event as efference.** Processors use it to bind contexts. Predictive attenuation of the self-caused change is not built until the raw-error readout shows it is needed.
10. **The self-model's embodiment record.** Self-location, body and perspective as labels (Blanke 2012), which makes the existing spec sentence true.
11. **The event contract is fixed.**
    - `perceptual_locus.changed` carries `locus`, `source` and `changed_by`.
    - `perceptual_locus.denied` carries `locus_requested`, `source_requested`, `denied_by` and `reason_label`.
    - The research allowlist matches both.
12. **The readout.** A per-viewing `perceptual_switching` welfare record, measured on raw prediction error, not the self-normalised one:
    - switches and refusals;
    - dwell times and the away share;
    - per switch: the transient, the adaptation time, new or revisited, and the arousal peak;
    - the savings ratio;
    - boredom after own switches compared with otherwise.
13. **Off equals absent**, checked against golden digests.
14. **Config names.** `[perceptual_locus]` throughout, which is what the code reads (`kaine/boot/factories/perceptual_locus.py:27`). The main spec's stale `[perception]` sentence is fixed here.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `perceptual-locus`: one source of truth with a derived locus and a locked writer path, the operator source route, the switch effector and arbiter with its gates, the welfare hold, the event fields, the self-model record, and the corrected config section of the self-switch requirement.
- `action-selection`: the stage-M switch act and its composition with the stimulus-control act.
- `vision-predictive` and `audition-predictive`: forward-model contexts per source, as a declared weight group.
- `evaluation-observers`: the `perceptual_switching` record, the allowlist fix, and the off-equals-absent checks.

## Impact

- **Code.**
  - `kaine/perception_state.py`: `source` and off-holders in desired state, the derived locus, `update_desired` with its `fcntl` lock, failed reads to the programme, and the gates.
  - `kaine/lifecycle/strategies.py`: `forward_model_bank` in the vision and audition weight groups.
  - `kaine/modules/sleep/module.py`, `kaine/cycle/__main__.py`, `kaine/lifecycle/gate_runner.py`: writers through `update_desired`.
  - `kaine/modules/perceptual_locus/module.py`: the arbiter, event fields.
  - A new `kaine/modules/effectors/perceptual_source.py`.
  - `kaine/workspace/stimulus_policy.py`, or a new `kaine/workspace/input_act_policy.py` that composes both stage-M sources.
  - `kaine/modules/affect/module.py`: credit for the switch effector.
  - `kaine/modules/vision/module.py` and `kaine/modules/audition/module.py`: the context bank.
  - `kaine/modules/self_model/`: the embodiment record.
  - `kaine/modules/sleep/module.py`: source restore.
  - `kaine/dashboard/perception.py`: the source route.
  - `kaine/evaluation/observers/research_event_observer.py` and the welfare observer.
  - `config/kaine.toml`: `[perceptual_locus]` gains `max_switches_per_awake_hour`, `min_dwell_new_source_s` and the welfare-hold window.
- **Docs.**
  - `docs/09-modules/perceptual-locus.md`, which also gets a rename of its stale `[perception]` wording.
  - `docs/09-modules/effectors.md`, `affect.md`, `self-model.md`, `vision.md`, `audition.md`.
  - `docs/17-research-data/README.md`.
- **Paper.** Via the revision notes: §3.5 and §3.6 (the entity's choice of source), A.4 (credit), A.6 (the composed stage-M rule), and Table A1 (dwell, new-source dwell, hourly cap, welfare-hold window).

## Dependencies and start condition

- **Depends on:**
  - `perceptual-sources`, for the registry and the single desired-state model (its task 2.9, moved there from this change);
  - `stimulus-control-act`, merged, for the composed stage-M source and the credit window it extends;
  - `effector-confinement` (branch `spec/grounding-social-safety-2026-10-31`), merged, with its amendment for a profile class that returns one declared request over the executor pipe, plus anti-replay (design D2). The same amendment serves `stimulus-control-act`.
  - `fork-merge-module-weights` (#638, merged in `1fd9268f`), whose weight groups gain `forward_model_bank`.
- **Stage L** depends on `act-intent-derivation` and `learned-action-selection`.
- **Joining an entity.** Turning it on for a running entity is a development-run component join: a two-layer opt-in, its second-review record, and the operator whitelisting the effector. Never inside a running study.
