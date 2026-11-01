# Design: perceptual-locus switching

## Context

The research note is `kaine-research/sensors-bodies-locus-research-2026-11-01.md`. Its section 8 draws six predictions for a mind whose source or body switches. Each decision below names the prediction it follows.

1. A switch brings a burst of prediction error wherever the new world violates the old predictions (Garrido, Kilner, Stephan and Friston 2009, *Clin Neurophysiol* 120:453-463). When the switch is self-caused, an efference copy is the innate route by which the change can be predicted (Blakemore, Wolpert and Frith 2000, *Neuroreport* 11:R11-R16).
2. Models are context-specific, selected by a cue and corrected by error (Wolpert and Kawato 1998, *Neural Netw* 11:1317-1329; Haruno, Wolpert and Kawato 2001, *Neural Comput* 13:2201-2220).
3. Control adapts fast and perception remaps slowly (Linden et al. 1999, *Perception* 28:469-481; Smith, Ghazizadeh and Shadmehr 2006, *PLoS Biol* 4:e179).
4. Returning to a known context shows savings, and one shared store shows interference (Krakauer, Ghez and Ghilardi 2005, *J Neurosci* 25:473-478). Alternating contexts becomes easier with practice (Welch et al. 1993, *Percept Psychophys* 54:195-204).
5. Learning a source needs acting in it (Held and Hein 1963, *J Comp Physiol Psychol* 56:872-876, from secondary sources; Kaspar et al. 2014, *Conscious Cogn* 28:47-63).
6. Ownership and presence form within minutes under synchronous feedback (Petkova and Ehrsson 2008, *PLoS ONE* 3:e3832; Slater et al. 2010, *PLoS ONE* 5:e10564). They are bounded by the contingencies a source affords (Slater 2009, *Phil Trans R Soc B* 364:3549-3557).

The motivational side follows the stimulus-control act's evidence (`stimulus-control-act` design, "Context"):

- Boredom is wanting but being unable to engage (Eastwood et al. 2012). It motivates new goals and experiences (Bench and Lench 2013), and it signals the opportunity cost of staying with the current activity (Agrawal, Mattar, Cohen and Daw 2022, *Psych Rev* 129:564-585).
- Control protects (Maier and Seligman 2016, *Psych Rev* 123:349-367).
- An act that pays immediately can capture behaviour (Olds and Milner 1954), and people choose aversive input over none (Wilson et al. 2014, *Science* 345:75-77). That is why the act is bounded.

## Decisions

### D1. The locus selects a source; the class follows

- Desired state gains `source`, a registered source id.
- `locus` becomes derived: it is the selected source's `locus_class`, or `off`.
- Physical XOR virtual, the real camera's privacy invariant, holds as before. A `physical` source runs only when the locus is `physical`, and the vision gate reads the source's class instead of the presence of a factory (`kaine/modules/vision/module.py:382-411`).
- `off` keeps its meaning: sleep sets it, and selecting a source again restores the class.
- With the registry off, `source` is never written and every path is today's.

The operator:

- `POST /diagnostics/perception/source {source, locked}` behind the operator token selects any registered, available source, bypassing the entity gates. The developmental lock still overrides it, as it overrides `/locus` today (`kaine/perception_state.py:220-235`).
- `POST /diagnostics/perception/locus` keeps working:
  - `off` as today.
  - `physical` or `virtual` select `[perceptual_sources].default_physical` or `default_virtual`.
  - A class with no default configured answers 409, naming the source route.

### D2. One act, one arbiter

- **The effector.** A `perceptual_source` effector is registered with the effectors module only when `[perception].allow_self_switch` is true and the registry is on.
  - It declares one parameter, `source`, whose allowed values are the registered ids, and a confinement profile with no host side effect: in process, no files, no network, no devices.
  - It runs only when the operator's whitelist names it.
- **The arbiter.** It realises the act by calling the arbiter. The arbiter is one object built at boot and shared with the `PerceptualLocus` module, which feeds it the inhibition state from each broadcast. The legacy `intent.perceptual_locus.switch` consumer stays and calls the same arbiter. It still has no producer.
- **Refusals and acceptance.**
  - A refusal is a failed `effectors.action` at the effectors module's alert salience, so the entity perceives that its act did not take, as with every failed act.
  - An accepted switch writes desired state atomically, bumps the source epoch and publishes `perceptual_locus.changed`.
- **Why the signed act path and not a new intent type.**
  - The act path already carries provenance, the whitelist, refusals as perception, and the hash-chained audit (spec `effectors`).
  - The stimulus-control act uses the same path (`stimulus-control-act` D3, D4).
  - A new intent type would duplicate all of it, without the audit.

### D3. The gates

Checked in this order, each refusal carrying its closed reason label:

| Gate | Reason label |
|---|---|
| the target is registered | `unknown_source` |
| it is available | `unavailable:<state>` |
| it is entity-selectable | `not_selectable` |
| it is not the current source | `already_there` |
| the locus is not locked | `locked_operator`, `locked_development` |
| `allow_self_switch` is true | `policy` |
| the last broadcast was not inhibited | `inhibited` |
| the entity is not asleep | `asleep` |
| the entity is mature | `developing` |
| no welfare hold is active | `welfare_hold` |
| `min_dwell_s` (30 s, as shipped) since the last switch, or `min_dwell_new_source_s` (120 s) when the current source was entered for the first time this run | `dwell` |
| fewer than `max_switches_per_awake_hour` (12) accepted entity switches in the trailing awake hour, excluding sleep and freezes | `hourly_cap` |

Values:

- **The new-source dwell.** The 120 s minimum on a never-seen source follows prediction 6: a full-body ownership illusion was rated after 2 minutes, with a threat response after 1 (Petkova and Ehrsson 2008).
- **The hourly cap.** It bounds a compulsive pattern. Each new source buys learning progress, and so curiosity priority (`interest-goal-factor`), and the cap stops that from becoming a loop. The cap mirrors the stimulus act's 20 seeks per awake hour, set lower because a switch is a far larger perceptual event than a seek.
- Both are provisional and go to Table A1.

### D4. The welfare hold

- The welfare observer watches for a gray-zone event or a protective action within `welfare_hold_window_s` (120 s) after an entity-initiated switch.
- When two of the last three entity switches were so followed:
  - the arbiter refuses entity switches with `welfare_hold`;
  - the operator gets an advisory;
  - the hold lasts until the operator lifts it.
- Operator switches are not held.
- This is raise-only welfare. It never forces a switch, and it only removes the entity's ability to throw itself into repeated large prediction-error events that are followed by distress.
- Loss of a source is handled by `perceptual-sources` (fallback after the grace period). It is not an entity switch.

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

### D6. Credit

- A realised switch is `effectors.action` for `perceptual_source` with `success = true`.
- Novelty labelled `other` (alert excess) and learning progress within `Delta_resp` after a realised switch count as the entity's own response for boredom, on both relief channels.
- This is the stimulus-control rule (`stimulus-control-act` D5), with the effector set widened to include `perceptual_source`. Outside the window, and with switching off, the rule is unchanged.

### D7. Forward-model contexts per source

The vision and audition processors each keep a bank keyed by source id. A context holds:

- the forward model, including its workspace-feedback wrap and its positive-control shadows, which are swapped with it;
- the rolling prediction-error window;
- the change-detector and habituation baselines;
- the attention schema's own forward model where one exists.

How the bank behaves:

- **On a new source epoch,** the processor stores its current context under the old id and binds the new id's context.
- **A never-seen source** gets a deep copy of the current context. Forks start from a copy of their parent, and a copy keeps whatever generic dynamics transfer. A fresh model would discard it.
- **Returning to a known source** binds its stored context: savings, no interference (prediction 4).
- **Size and persistence.**
  - The bank is bounded by the registered sources.
  - It is serialised as the single model is today (`module.py:986-999`): weights plus statistical summaries, never a raw latent.
  - A preservation bundle carries the whole bank, because the world model is identity.
- **The transient.**
  - A switch to a never-seen source starts with the copied baseline, so the first frames of a different world are normalised against the old world's error level. The burst is real.
  - The rolling window then absorbs it: 32 reports, about 3 s at the shipped 10 Hz.
  - A switch to a known source normalises against that source's own baseline, so its burst is small when the world is as it was.
- **Stage 2, not built here: selection among contexts by prediction error** (MOSAIC's online correction, Haruno et al. 2001).
  - It is needed when a source's world changes under its label, such as a different game in the same stream or a new room for the webcam.
  - The readout's adaptation times show whether that happens.

### D8. The efference copy, and what is not built

- `perceptual_locus.changed` with `changed_by = "entity"` is the efference copy of the act.
- The processors use the source epoch to bind contexts, which is MOSAIC's contextual cue.
- Predictive attenuation of a self-caused transient is an innate mechanism with cited neuroscience (Blakemore et al. 2000). It would be allowed at the code site, but it is not built: the transient is information the entity can learn from, and the credit window and the readout measure it first.

### D9. The self-model's embodiment record

- On `perceptual_locus.changed`, the self-model module records three labels (Blanke 2012, *Nat Rev Neurosci* 13:556-571; Kilteni, Groten and Slater 2012, *Presence* 21:373-387):
  - `self_location`, the source id;
  - `body`, the paired body or `none`;
  - `perspective`, the camera name or `none`.
- This makes the existing spec sentence true. It holds labels only.

### D10. Sleep

- Sleep keeps writing `off` and restoring the pre-sleep locus (spec `perception-feed`). With the registry on, `source` is untouched by the `off` write (`write_desired_locus` replaces only the locus, `perception_state.py:205-237`), and restore returns to the pre-sleep source.
- A source that became unavailable during sleep falls back as in `perceptual-sources`.

### D11. Event fields and the readout

- **Event fields.**
  - `perceptual_locus.changed`: `{locus, source, changed_by}`, where `changed_by` is one of `entity`, `operator`, `source_lost` or `sleep`.
  - `perceptual_locus.denied`: `{locus_requested, source_requested, denied_by, reason_label}`, where `denied_by` is `arbiter`.
  - The research allowlist gains `source` and `source_requested`. The renamed fields match what it already expects.
- **The `perceptual_switching` welfare record.** One per viewing, as listed in the proposal (item 10). The adaptation time is the time from the switch until the processor's normalised error stays below 1.5 for 10 consecutive reports. It is computed per processor and recorded with whether the context was new or revisited. The savings ratio is the adaptation time on a revisit over the first visit's.
- **What the readout answers.** Whether prediction 4 holds for this mind: return should be faster than first entry. If it does not, the context bank is not doing its job, and stage 2 is due.

### D12. Off equals absent

- With `[perception].allow_self_switch = false` (shipped), none of these is constructed:
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
  - dwell and the hourly cap;
  - savings make revisits less rewarding, as learning progress falls;
  - the readout's switch rate;
  - the welfare hold.
- **[A switch into the operator's room surprises the operator.]**
  - `operator_room` sources are not entity-selectable unless the operator opts in. On the reference host the CTO opted in on 2026-11-01 for the webcam, so there the entity may choose the room. Each such switch still passes every gate of D3, and it is recorded.
  - The on-air state and the camera's light show it.
- **[The context bank grows the preservation bundle.]** It is bounded by the registered sources, and each context is the size of today's model.
- **[Interference stays hidden.]** The readout's savings ratio exposes it.
- **[Stage-M composition biases toward the larger act set.]** Stated in D5, and replaced in stage L.

## Welfare and privacy

- **Welfare-high-risk.** This changes what the entity perceives at its own choice, and a switch is a large prediction-error event. Every PR needs an independent second review, one supervised validation boot on a branch before the join, and the welfare net on.
- **The entity can never:**
  - switch during its developmental phase;
  - switch while asleep;
  - choose the operator's desktop;
  - close its senses: `off` is not a target;
  - be left without senses after a source is lost.
- **The operator always can:** override, lock, and lift a welfare hold.
- **Records** carry ids, labels and numbers only. Device identities are hashed, as in `perceptual-sources`.

## Estimate (LLM-agent terms)

- Size M:
  - arbiter, effector, gates, events and dashboard route: about 700 lines plus 900 of tests;
  - stage M and its composition: about 250 plus 400;
  - context bank in vision and audition: about 500 plus 700;
  - self-model record, sleep and readout: about 400 plus 500.
- About three agent-days, plus the validation boot.
