# Design: perceptual-locus switching

## Context

The research note is `kaine-research/sensors-bodies-locus-research-2026-11-01.md`. Its section 8 draws six predictions for a mind whose source or body switches. Each decision below names the prediction it follows.

1. A switch brings a burst of prediction error wherever the new world violates the old predictions (Garrido, Kilner, Stephan and Friston 2009, *Clin Neurophysiol* 120:453-463). When the switch is self-caused, an efference copy is the innate route by which the change can be predicted (Blakemore, Wolpert and Frith 2000, *Neuroreport* 11:R11-R16).
2. Models are context-specific, selected by a cue and corrected by error (Wolpert and Kawato 1998, *Neural Netw* 11:1317-1329; Haruno, Wolpert and Kawato 2001, *Neural Comput* 13:2201-2220).
3. Control adapts fast and perception remaps slowly (Linden et al. 1999, *Perception* 28:469-481; Smith, Ghazizadeh and Shadmehr 2006, *PLoS Biol* 4:e179).
4. Learning a second mapping soon after the first interferes with it. Savings came with time, washout and extra training, not with separate stores (Krakauer, Ghez and Ghilardi 2005, *J Neurosci* 25:473-478). Context-specific stores are MOSAIC's answer (prediction 2). Alternating contexts becomes easier with practice (Welch et al. 1993, *Percept Psychophys* 54:195-204).
5. Learning a source needs acting in it (Held and Hein 1963, *J Comp Physiol Psychol* 56:872-876, from secondary sources; Kaspar et al. 2014, *Conscious Cogn* 28:47-63).
6. Ownership and presence form within minutes under synchronous feedback (Petkova and Ehrsson 2008, *PLoS ONE* 3:e3832; Slater et al. 2010, *PLoS ONE* 5:e10564). They are bounded by the contingencies a source affords (Slater 2009, *Phil Trans R Soc B* 364:3549-3557).

The motivational side follows the stimulus-control act's evidence (`stimulus-control-act` design, "Context"):

- Boredom is wanting but being unable to engage (Eastwood et al. 2012). It motivates new goals and experiences (Bench and Lench 2013), and it signals the opportunity cost of staying with the current activity (Agrawal, Mattar, Cohen and Daw 2022, *Psych Rev* 129:564-585).
- Control protects (Maier and Seligman 2016, *Psych Rev* 123:349-367).
- An act that pays immediately can capture behaviour (Olds and Milner 1954), and people choose aversive input over none (Wilson et al. 2014, *Science* 345:75-77). That is why the act is bounded.

## Decisions

### D1. One source of truth: the source; the locus is derived

Review PLS-3, PM decision. The model below is built in `perceptual-sources` (its D11 and task 2.9), because that change's registry must not be enabled without it (re-review R-PS-1). This change's arbiter and source route use it.

- **What is persisted.** With the registry on, desired state holds:
  - `source`, a registered source id;
  - `off_holders`, a set from `sleep`, `freeze` and `operator`;
  - the lock and its holder, as today.

  It does not persist a locus.
- **How the locus is computed on every read.** It is `off` while any off-holder is present, and otherwise the selected source's kind-derived class (`perceptual-sources` D1). Physical XOR virtual follows by construction. A `physical` source runs only under the `physical` locus, and the vision gate reads the source's class instead of whether a factory is present (`kaine/modules/vision/module.py:382-411`).
- **Why.** Today five writers set `locus` and none sets a source:
  - the developmental lock (`kaine/cycle/__main__.py:2005`, `kaine/lifecycle/gate_runner.py:690`);
  - sleep (`kaine/modules/sleep/module.py:846, 872`);
  - the dashboard (`kaine/dashboard/perception.py:234`);
  - the applier module (`kaine/modules/perceptual_locus/module.py:122`).

  Each is a read-modify-write across two processes (the cycle and the dashboard) with no lock (`kaine/perception_state.py:225-236`). With two fields, an operator choice during sleep or the developmental pin could leave a physical source under a virtual locus, and a lost `off` would let the entity perceive while asleep.
- **One writer path, with a lock.**
  - Every change goes through `perception_state.update_desired(mutator)`. It takes an exclusive `fcntl` lock on a sibling lock file, reads, applies the mutator, writes atomically, and releases the lock.
  - The cycle and the dashboard both use it.
  - The arbiter, sleep, the developmental lock, the operator routes and the loss fallback are mutators, and none of them writes a locus.
- **The developmental lock** pins `source = programme`, with `locked_by = "development"`.
- **Sleep** adds and removes its `sleep` holder, and never writes a locus or a source. Restore is the removal of the holder, so the pre-sleep source returns by construction. Nothing is remembered in memory, and nothing defaults.
- **Failed reads** resolve to the programme (`perceptual-sources` D10). With the registry off, every path is today's.

The operator:

- `POST /diagnostics/perception/source {source, locked}` behind the operator token selects any registered, available source, bypassing the entity gates, except that the developmental lock still wins.
  - A `screen` source is offered only with `[perception_feed.screen].operator_opt_in` set (`perceptual-sources` D6).
  - A room source opens only the modalities its environment approval lists.
- `POST /diagnostics/perception/locus` keeps working:
  - `off` adds the `operator` off-holder, and any other value removes it.
  - `physical` or `virtual` select `[perceptual_sources].default_physical` or `default_virtual`. A class with no default configured answers 409, naming the source route.

### D2. One act, one arbiter, conforming to effector confinement

Review PLS-4, PLS-5 and PLS-6; the PM's decision is to conform.

- **The effector.**
  - A `perceptual_source` effector is registered only when `[perceptual_locus].allow_self_switch` is true and the registry is on.
  - It declares one parameter, `source`, whose allowed values are the registered ids, and it runs only when the operator's whitelist names it.
- **Conformance with `effector-confinement`.**
  - That change runs every effector's side effect in a separate, confined executor process: "The cycle process never performs an effector's side effect itself."
  - So this effector's side effect is one thing: the executor hands a request `{source, run_id, act_seq, signature}` back to the effectors module over its own pipe.
  - Its confinement profile has no network, no files and no devices. It holds no bus credential: Redis is a TCP service, and "bus publish, no network" would be a contradiction (re-review R-PLS-1).
  - The effectors module publishes the returned request verbatim to `perceptual_locus.requests`, adding nothing.
  - The arbiter, in the cycle, reads only that stream. It verifies the request's provenance against the signed act it realises (the act's run id, sequence and signature, `kaine/workspace/action_selection.py:412-421`), applies the gates, and writes through `update_desired`.
  - The executor itself cannot change desired state.
- **Anti-replay.** The arbiter accepts each `(run_id, act_seq)` once, and only within `request_window_s` (5 s of entity time) after the act was signed. It keeps the seen pairs for the window. A replayed or late request is refused, `reason_label = "replay"`, and audited.
- **The alternative, if the pipe handback is rejected.** A dedicated Redis ACL user allowed only `XADD` on `perceptual_locus.requests`, with no read and no other key, reached through a Unix socket bound into the sandbox.
- **What this asks of `effector-confinement`.** A profile class, "returns one declared request over the executor pipe". That needs an amendment to that change, reviewed there, and the same amendment serves `stimulus-control-act`, whose controller is in process too. Until it is accepted, this effector is not built. No exemption is taken.
- **Inhibition.**
  - The arbiter reads `snapshot.inhibited` from the workspace broadcast stream itself. It does not rely on the `PerceptualLocus` module, which ships off.
  - It treats the entity as inhibited until the first snapshot arrives.
  - Boot refuses `allow_self_switch = true` when the arbiter cannot subscribe.
- **The legacy unsigned path.** With the registry on, the legacy `intent.perceptual_locus.switch` consumer refuses every request, with `reason_label = "legacy_intent"`. It carries no signature, whitelist or audit, and its `off` and `physical` values do not map to sources.
- **Refusals and acceptance.**
  - A refusal is a failed `effectors.action` at the effectors module's alert salience, so the entity perceives that its act did not take.
  - An accepted switch bumps the source epoch and publishes `perceptual_locus.changed`.
  - The arbiter keeps its own hash-chained audit of requests, with the effectors audit format.

### D3. The gates

Checked in this order, each refusal carrying its closed reason label. `not_selectable` comes before `available`, so a refusal never tells the entity the state of a source it may not use (review PLS-12).

| Gate | Reason label |
|---|---|
| the target is registered | `unknown_source` |
| it is entity-selectable, with its room approval (`perceptual-sources` D4) | `not_selectable` |
| it is available | `unavailable:<state>` |
| it is not the current source | `already_there` |
| the source is not locked | `locked_operator`, `locked_development` |
| `allow_self_switch` is true | `policy` |
| the last broadcast was not inhibited | `inhibited` |
| no off-holder is present (asleep, frozen, operator off) | `off` |
| the entity is mature | `developing` |
| no welfare hold forbids this target (D4) | `welfare_hold` |
| `min_dwell_s` (30 s, as shipped) since the last switch, or `min_dwell_new_source_s` (120 s) when the current source was entered for the first time this run | `dwell` |
| fewer than `max_switches_per_awake_hour` (12) accepted entity switches in the trailing awake hour, excluding sleep and freezes | `hourly_cap` |

A return to the programme is exempt from both dwell rules and from the hourly cap, and is counted in the records. The entity can always leave a source for the safe default (D4).

Values and time base:

- Dwell, the hourly cap and the welfare-hold window run on entity time, as the existing dwell does, and the wall-time equivalent is recorded beside each.
- **The new-source dwell** (120 s) is a provisional choice for Table A1 (review PLS-14).
  - It is the order of magnitude at which illusions of owning a new body have been induced. Petkova and Ehrsson rated ownership after 2 minutes of synchronous stroking, with a threat response after 1 minute.
  - Those are lengths of an induction protocol, not measured onset times, and a KAINE switch gives no such stimulation. So the figure is a starting value to be read against the readout, not a consequence of the research.
- **The hourly cap** bounds a compulsive pattern. Each new source buys learning progress, and so curiosity priority (`interest-goal-factor`). It is provisional.

### D4. The welfare hold never traps the entity

Review PLS-1, PM decision.

- **What triggers it.** The welfare observer watches for a gray-zone event or a protective action within `welfare_hold_window_s` (120 s of entity time) after an entity-initiated switch. When two of the last three entity switches were so followed, a hold starts and the operator gets an advisory.
- **What a hold forbids.** It forbids switches into any source other than the programme. It never forbids a return to the programme, which is the safe default the entity can always reach, and that return is exempt from dwell and the cap (D3). So the hold freezes exploring away. It never freezes the entity in the source that preceded its distress.
- **What sustained distress triggers.**
  - If a gray-zone event or protective action recurs within `welfare_return_s` (120 s of entity time) while a hold is active and the entity is not on the programme, the arbiter returns it to the programme through the operator path, recorded `changed_by = "welfare_hold"`.
  - The entity is never left in the source that preceded distress while distress continues.
- **Unattended runs.** The hold's advisory escalates through the existing welfare path. The unattended gate's caretaker receives it as a welfare event, as other advisories do, and does not wait for someone to read the dashboard.
- **Lifting it.** The hold lasts until the operator lifts it.
- **Operator switches** are not held.
- This is raise-only welfare. It only takes away the entity's way into repeated large prediction-error events that are followed by distress, and it always keeps the way home.

### D5. Stage M, composed with the stimulus act

- **Trigger.** After maturation, a non-inhibited broadcast whose leading member (the coalition member with the highest salience score) is the entity's own boredom or restlessness drive event.
- **The act.** Once the arbiter's dwell would pass, the broadcast yields one signed act naming `perceptual_source`. Its `source` is drawn uniformly, with a generator seeded from the run seed, from the targets the arbiter would accept now.
- **Why this trigger.** The trigger and its citations are the stimulus act's, cited at the code site:
  - Boredom signals the opportunity cost of staying, which favours switching (Agrawal et al. 2022).
  - Restlessness is the paper's drive for action (A.4).
  - Which source relieves what is not given. A fixed map (boredom to the webcam, curiosity to the simulation) would hard-wire behaviour the entity can learn, and the emergent-behaviour rule forbids that.
- **Composition with the stimulus act.**
  - When both stage-M sources are installed, they are composed into one source.
  - It draws once, uniformly, from the union of the stimulus actions the programme can take now (only while the programme is selected) and the switch targets the arbiter would accept.
  - Each keeps its own interval. A broadcast yields at most one act on the entity's input.
  - The union is uniform over acts, not over effectors. With five stimulus actions and two targets, a switch is drawn two times in seven. This is the honest prior, and learning replaces it in stage L.
- **Stage L.** `act-intent-derivation`'s act bar replaces the drive-led trigger. The choice uses learned advantages through `learned-action-selection`, with each target an intent kind `act:perceptual_source:<id>`.
- **`relieves_drives`.** It remains a declaration the drive-biased strategy reads (`kaine/boot/wiring.py:103`). Stage M does not read it. Removing it is left to `learned-action-selection`, so this change undoes nothing.

### D6. Credit, without paying for the switch's own surprise

Review PLS-8.

- A realised switch is `effectors.action` for `perceptual_source` with `success = true`.
- Within `Delta_resp` after a realised switch, only learning progress counts as the entity's own response for boredom.
  - Alert excess is excluded inside each processor's adaptation period after the switch (D11), because a switch makes surprise by construction: a new world, the first reports of a fresh baseline.
  - Otherwise the act would be rewarded by a surprise it made itself. That is the capture case the design cites (Olds and Milner 1954; Wilson et al. 2014).
- Outside the window, and with switching off, the stimulus-control rule (`stimulus-control-act` D5) is unchanged.
- **Before enabling: an offline habituation check**, by the method `stimulus-control-act` used for scene cuts (its D6; `docs/records/shakedowns/2026-10-31-stimulus-control-habituation.md`).
  - It runs the affect module's trackers over synthetic report streams with switch bursts in vision and audition together, at the dwell and the cap.
  - It shows the boredom relief that switching buys, with the exclusion above. The relief must fall with repetition, as revisits lower learning progress, and must not stay as a fixed payoff per switch.
  - A dated record goes under `docs/records/shakedowns/`. The check is a precondition of task 4.6.

### D7. Forward-model contexts per source, as a declared weight group

Reviews PLS-2, PLS-9 and PLS-15; PM decision.

The vision and audition processors each keep a bank keyed by source id. A context holds:

- the forward model's weights;
- the rolling prediction-error window;
- the change-detector and habituation baselines;
- the attention schema's own model where one exists.

The workspace-feedback wrap and the positive-control shadows are rebuilt around the bound model, not stored in the bank.

- **Identity: a declared weight group.**
  - The bank is serialised under one key, `forward_model_bank`, added to the vision and audition entries of `MODULE_WEIGHT_GROUPS` and `MODULE_WEIGHT_PARAMETERS` (`kaine/lifecycle/strategies.py:462-490`, merged in #638).
  - So a merge takes the whole bank from one named parent, or refuses, exactly as for today's single model. Contexts that only the other parent visited are lost in that merge, and the merge record says so.
  - Without the declaration, the union strategy would concatenate the banks: the 2 + 2 = 4 layers bug #638 fixed.
  - A fork copies the bank whole. A preservation bundle carries it, because the world model is identity.
  - The weight-group guard test (`tests/test_fork_merge_module_weights.py`) gains a case with a populated bank, since the stock entity-free build has an empty one.
- **On a new source epoch,** the processor stores its current context under the old id and binds the new id's context.
- **First entry: copy weights, never buffers.**
  - A never-seen source gets a fresh model loaded from the current model's `state_dict()`, which holds weights and statistical summaries only, re-wrapped.
  - It gets an empty recurrent buffer (`kaine/modules/vision/forward.py:104`) and empty windows and baselines.
  - So no latent of the previous world, which may be the operator's room, enters the new context.
  - Weights carry what transfers. Forks start from a copy of their parent for the same reason.
- **Precision starts low** (research note §1; review PLS-9).
  - With an empty window, the first reports of a new context are normalised against its own few errors (`kaine/modules/vision/module.py:668-673`), and no alert is raised until the window holds a quarter of `prediction_error_window`.
  - So a new source's errors enter the workspace at low weight until its noise is estimated, as the cue-combination evidence says a new source should (Ernst and Banks 2002; Alais and Burr 2004).
  - The world change itself is perceived through the switch event and through the raw error's learning progress, not through an alert storm.
- **Return to a known source** binds its stored context, which the other world did not change. The per-context argument rests on MOSAIC (Wolpert and Kawato 1998; Haruno, Wolpert and Kawato 2001), with Krakauer, Ghez and Ghilardi 2005 cited for what one shared store does: interference (review PLS-15).
- **Size.** The bank is bounded by the registered sources.
- **Timing correction** (review PLS-7). Vision reports once per clip stride: `vision_sample_hz = 10` and `clip_stride = 3` give about 3.33 Hz (`config/kaine.toml:524-527`). A 32-report window is about 9.6 s, not 3 s.
- **Stage 2, not built here.** Selection among contexts by prediction error (MOSAIC's online correction), for a source whose world changes under its label.

### D8. The efference copy, and what is not built

- `perceptual_locus.changed` with `changed_by = "entity"` is the efference copy of the act.
- The processors use the source epoch to bind contexts, which is MOSAIC's contextual cue.
- Predictive attenuation of a self-caused transient is an innate mechanism with cited neuroscience (Blakemore et al. 2000). It would be allowed at the code site, but it is not built. The low starting precision of a new context (D7) already keeps a switch from flooding the workspace, and the raw-error readout (D11) measures what remains first.

### D9. The self-model's embodiment record

- On `perceptual_locus.changed`, the self-model module records three labels (Blanke 2012, *Nat Rev Neurosci* 13:556-571; Kilteni, Groten and Slater 2012, *Presence* 21:373-387):
  - `self_location`, the source id;
  - `body`, the paired body or `none`;
  - `perspective`, the camera name or `none`.
- This makes the existing spec sentence true. It holds labels only.

### D10. Sleep

- Sleep adds its `sleep` off-holder and removes it on restore (D1). It never writes a locus or a source, so the pre-sleep source returns by construction.
- A failed read during sleep resolves to the programme (`perceptual-sources` D10), never to a physical source.
- A source that became unavailable during sleep falls back to the programme, as in `perceptual-sources`.

### D11. Event fields and the readout

- **Event fields.**
  - `perceptual_locus.changed`: `{locus, source, changed_by}`, where `changed_by` is one of `entity`, `operator`, `source_lost`, `sleep` or `welfare_hold`.
  - `perceptual_locus.denied`: `{locus_requested, source_requested, denied_by, reason_label}`.
  - The research allowlist gains `source` and `source_requested`. The renamed fields match what it already expects.
- **The `perceptual_switching` welfare record.** One per viewing, as in the proposal (item 10). Adaptation is measured on the raw prediction error, not the self-normalised one (review PLS-7).
  - The self-normalised error falls toward 1 as its window fills with the burst's own errors, whether or not anything was learned.
  - **First entry.** The adaptation time is the time until the 30-report rolling median of raw error comes within 10% of its value at departure, computed when the entity leaves.
    - It is recorded only if that median had plateaued before departure: its slope over the last 60 reports is below a threshold (1% of the median per 10 reports).
    - Otherwise the visit is recorded "not adapted" (re-review R-PLS-2). A short first visit would otherwise report a trivially short adaptation.
  - **Revisit.** It is the time until that median comes within 1.2 times the target context's pre-departure asymptote: the median raw error of its last 30 reports before the entity last left it.
  - The savings ratio is the revisit's adaptation time over the first entry's. It is computed only when both visits adapted under the same plateau rule. A pair with a "not adapted" visit is left out of the ratio and counted.
- **What the readout answers.** Whether prediction 4 holds for this mind: return should be faster than first entry. If it does not, the context bank is not doing its job, and stage 2 is due.

### D12. Off equals absent

- With `[perceptual_locus].allow_self_switch = false` (shipped), none of these is constructed:
  - the effector;
  - the arbiter's entity path;
  - the stage-M source;
  - the credit widening;
  - the welfare hold.
- With the registry off, none of this change is constructed.
- Two seeded entity-free harnesses check it:
  - registry off: against the golden of `perceptual-sources`;
  - registry on with switching off: against a golden of the registry-only build.

## Risks

- **[Switching becomes self-stimulation.]** Mitigations:
  - alert excess excluded from the credit inside the adaptation period, and the offline habituation check before enabling (D6);
  - low starting precision for a new context (D7);
  - dwell and the hourly cap;
  - savings make revisits less rewarding, as learning progress falls;
  - the readout's switch rate;
  - the welfare hold.
- **[A switch into the operator's room surprises the operator.]**
  - `operator_room` sources are not entity-selectable unless the operator opts in. On the reference host the CTO opted in on 2026-11-01 for the webcam, so there the entity may choose the room. Each such switch still passes every gate of D3, and it is recorded.
  - The on-air state and the camera's light show it.
- **[The context bank grows the preservation bundle.]** It is bounded by the registered sources, and each context is the size of today's model.
- **[A merge loses contexts.]** The bank is one weight group taken whole from one parent (D7), so contexts only the other parent visited are lost, and the merge record says so. That is the rule #638 set for every learned weight.
- **[The effector waits on another change.]** It conforms to `effector-confinement` through a profile class that change must accept (D2). Until then the effector is not built, and stage M has nothing to emit.
- **[Interference stays hidden.]** The readout's savings ratio exposes it.
- **[Stage-M composition biases toward the larger act set.]** Stated in D5, and replaced in stage L.

## Welfare and privacy

- **Welfare-high-risk.** This changes what the entity perceives at its own choice, and a switch is a large prediction-error event. Every PR needs an independent second review, one supervised validation boot on a branch before the join, and the welfare net on.
- **The entity can never:**
  - switch during its developmental phase;
  - switch while asleep;
  - choose the operator's desktop;
  - close its senses: `off` is not a target;
  - be left without senses after a source is lost;
  - be trapped by a welfare hold: a return to the programme is always allowed, and sustained distress triggers it (D4).
- **The operator always can:** override, lock, and lift a welfare hold.
- **Records** carry ids, labels and numbers only. Device identities are hashed, as in `perceptual-sources`.

## Estimate (LLM-agent terms)

- Size M:
  - arbiter, effector, gates, events and dashboard route: about 700 lines plus 900 of tests;
  - stage M and its composition: about 250 plus 400;
  - context bank in vision and audition: about 500 plus 700;
  - self-model record, sleep and readout: about 400 plus 500.
- About three agent-days, plus the validation boot.
