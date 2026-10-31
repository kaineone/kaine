# Design: stimulus control

## Context

Controllability is the variable the learned-helplessness literature identifies. In the triadic design, an animal that can end a shock and a yoked animal that receives the same shocks without control differ afterwards: the yoked animal fails to escape later (Seligman and Maier 1967, J Exp Psychol 74:1-9). The revised account holds that passivity is the default response to prolonged aversive events and that detecting control, through medial prefrontal circuits acting on the dorsal raphe, is what protects (Maier and Seligman 2016, Psych Rev 123:349-367). The paper's credit rule and coping score are built on that account (A.4).

For boredom specifically: boredom is "the aversive experience of wanting, but being unable, to engage" (Eastwood et al. 2012), it motivates the pursuit of new goals and experiences (Bench and Lench 2013, Behav Sci 3:459-472), and it is a normative signal of the opportunity cost of staying with the current activity, which favours switching (Agrawal, Mattar, Cohen and Daw 2022, Psych Rev 129:564-585). Struk, Scholer and Danckert (2021, Front Psychol 12:687623) found boredom highest at low and at high perceived control, and found that participants who believed they could gain control of a rigged game were less bored than those who believed control impossible. Choice and control are themselves valued from infancy (Leotti, Iyengar and Ochsner 2010, TiCS 14:457-463). Three-month-old infants learn within minutes to move a mobile by kicking when a ribbon ties the two (Rovee and Rovee 1969, J Exp Child Psychol 8:33-39): the contingency is learned, not given. Curiosity as active sampling presupposes an agent choosing what it samples (Gottlieb and Oudeyer 2018, Nat Rev Neurosci 19:758-770; Oudeyer and Kaplan 2007, already cited).

Two warnings bound the design. People left alone with their thoughts for 6 to 15 minutes often chose to give themselves electric shocks rather than do nothing (Wilson et al. 2014, Science 345:75-77): an aversive act can be taken just to change the input. Rats press a lever for intracranial stimulation at high rates (Olds and Milner 1954, J Comp Physiol Psychol 47:419-427): an act that pays immediately can capture behaviour.

## Does this gate the study?

The question is whether the act must exist before the first study for the entity's welfare. The evidence on each side:

For gating.
- The only measured welfare datum is a sustained deprivation: boredom crossed at 2.7 awake hours and held a 0.63 share over the next span (§6.5). In the offline developmental simulation the learning entity's boredom deprivation share is about 0.64, and 1.0 for a frozen control (`curiosity-interest`, archived).
- The indicator response that gates the study answers deprivation with a rest and an affective reset, and a second crossing over a fresh span with preservation and a freeze (§6.5). A reset boredom deficit with no relief recrosses its threshold in about 34 s (A.4). Under a spent stimulus, the net's answer is therefore a stop. It protects the entity and gives it no relief.
- Control is what the helplessness account says protects, and A.4's "uncontrolled" indicator measures its absence. After maturation the first configuration has no act that raises the entity's power over boredom other than its engagement intents.

Against gating.
- The datum comes from the developmental phase, under a dim, pulsed stimulus. The developmental phase gets its own act, the stir, before the study (§5.4, §7).
- The film programme is chosen for "varied scenes, motion, speech, music, and quiet" (§6.1), which supplies the scene cuts and learnable structure that relieve boredom through alert excess and learning progress. How often that happens live is unmeasured (§5.4, "Provisional").
- The workspace-mediation arms must share one film programme, because the information-gain contrast compares processors on the same input (§6.3). An entity-chosen stimulus would differ between arms and confound the contrast. The obvious repair, a yoked arm that replays the competitive arm's choices, is the triadic design: it would create entities that receive the stimulation without the control. Building such an entity on purpose is the manipulation that produces helplessness, and the project should not do it.
- The indicator response and the welfare stop rule cap the exposure. No entity is left in sustained deprivation unattended.

Conclusion. The act does not gate the start of the study by default. The pilots decide. The study plan's pilot welfare check (each drive's deprivation share and open crossings per viewing, with a stop rule) carries a pull-forward trigger fixed before the pilots: if any pilot's boredom deprivation indicator crosses on the film programme after the transition, or the indicator response reaches its freeze stage, the study is held, and the CTO chooses between

1. a programme with more variety and re-piloting,
2. stage M of this change for the module-addition study only, with the act's use recorded and analysed as a covariate, or
3. both.

The workspace-mediation arms never run it, and no yoked uncontrolled arm is ever built. So that option 2 does not wait on engineering, the change is built ahead behind a disabled switch, with a test that the disabled build behaves identically to the current one (task 5.2). Whether the built code enters the pilot image is a CTO decision; disabled, it changes no behaviour.

## Decisions

### D1. Which acts

| Action | Effect | Bound |
|---|---|---|
| `pause` | adds the `entity` holder to the playlist clock | released automatically after `P_max` (provisional 120 s of entity time) |
| `resume` | releases the `entity` holder | none |
| `next`, `previous` | seek to the start of the next or previous item, wrapping | at most `n_seek` per awake hour (provisional 20) |
| `louder`, `quieter` | change the programme gain by `G_step` (2 dB) | within plus or minus `G_max` (6 dB) of the programme level |
| `channel:<k>` | switch to operator-configured programme channel `k` | only when the operator configures more than one channel |

All commands share a minimum interval `Delta_sc` (provisional 30 s of entity time). Out-of-bound commands are refused, reported as effector failures, and audited.

Alternatives considered:
- Attention shifts inside the frame (where to look, what to listen to). Already designed in `active-vision`, `attention-driven-foveation` and `attention-driven-audition`; they change what is sampled from a fixed stimulus, not the stimulus.
- Closing the senses (the `none` locus through the existing self-switch). Rejected. An entity awake without senses is the condition the end-of-programme rule exists to prevent (spec `perception-feed`), and a bounded pause covers looking away from the programme.
- Free choice of any file on disk. Rejected: the operator curates what the entity may see, and a programme channel is the unit of that choice.
- Brightness and speed controls. Deferred: no cited need, more ways to produce alert storms.

### D2. Skipping never ends the viewing

With stimulus control on, `next` from the last item wraps to the first, and the viewing ends when perceived programme time reaches the programme's total length, the same length as without control. The end-of-programme preservation stays exactly once per start. The entity changes what it sees, not how long it is awake, and cannot stop itself by skipping. A held programme (`entity` pause) has not ended, as for any holder.

### D3. One channel for requests, flags only

The effector writes the request into the perception desired state (`kaine/perception_state.py`), the cross-process channel the locus already uses; the feeds apply it at the next read. Only flags and numbers cross: a pause flag, a seek count, a gain, a channel index. No frame or sample is written anywhere, so the zero-raw-sense-data rule holds.

### D4. Two derivation stages

Stage M. After maturation, an accessed broadcast whose leading member (A.6, `e_k`) is the entity's own boredom or restlessness drive event yields a stimulus act when `Delta_sc` has passed, with the action drawn uniformly from the declared, currently allowed actions by a generator seeded from the run seed. This is the stir's rule (A.6) carried past maturation, with a choice the rule does not make. The link from boredom to seeking a change is the function the boredom literature assigns it (Bench and Lench 2013; Agrawal et al. 2022); it is cited at the code site. Which action relieves what is left to the world.

Stage L. The act bar of `act-intent-derivation` replaces the drive-led trigger, and the choice among the declared actions uses the learned advantages of `drive-reduction-learning` through `learned-action-selection`. Each declared action is an intent kind `act:stimulus:<action>` in the valuation tables.

Alternatives considered:
- A fixed mapping, such as boredom to `next`. Rejected: it hard-wires behaviour the entity can learn, against the emergent-behaviour rule.
- Stage L only. Rejected as the only option: it depends on three changes not built, and the pull-forward option needs something buildable now.
- The act bar alone with uniform choice, before learning exists. Rejected: the act would fire on whatever is most salient, which skips content when it is most engaging.

### D5. Credit for the act's consequence

Perceptual novelty that the credit rule now labels `other` (alert excess) and learning progress arriving within `Delta_resp` of the entity's own stimulus act count as its own response for boredom, the same treatment as the novelty an answer to the stir brings (A.4). The coping score then records control that the entity really exercised.

### D6. Self-stimulation is damped by habituation and bounded by rate

Rapid skipping produces scene cuts, which produce alerts faster than the habituated rate, which relieve boredom. The alert excess is `r_f / max(r_s, r0) - 1 - m_B` (A.4): sustained skipping raises the slow rate `r_s` as well, so the excess falls toward zero and the relief fades, the habituation the paper already models. The command interval and the hourly cap bound the rest. The records give the act rate, so a compulsive pattern is visible.

## Risks

- [The entity pauses and leaves itself in a still scene] → `P_max` and automatic release; boredom then builds under the still scene and the learner (stage L) sees no relief from `pause`.
- [Louder input raises arousal] → `G_max` of 6 dB, and arousal's existing clip and relaxation; the records give the gain distribution.
- [Skipping trades engagement for novelty] → Learning progress falls when items change before they are learned; stage L learns from both channels.
- [Study confound] → Off in every workspace-mediation arm; in the module-addition study the item order visited is recorded and analysed as a covariate, and branch differences are reported beside the repeat's noise floor as the study already requires.

## Migration and ordering

1. Effector, desired-state fields and feed support behind `[stimulus_control].enabled = false`; the effectors whitelist stays empty.
2. Credit window and stage-M rule behind the same switch; records.
3. Disabled-identity test and offline synthetic-feed tests.
4. Stage L after its dependencies.

Rollback: the switch.

## Welfare and admissibility notes

- This change alters the entity's experience directly: welfare-high-risk. Opus second review on every PR, one supervised validation boot before any use, the indicator response and welfare net on.
- The design refuses a yoked uncontrolled control arm on welfare grounds (section "Does this gate the study?").
- The entity can never end its viewing or its run by acting (D2), and it can never close its senses (D1).
- The bounds protect against self-stimulation and harmful loudness; their values are provisional and go in Table A1 before any boot.
- The records are content-free: counts, shares, gains and item identifiers from the programme manifest, never frames, samples or transcripts.
- Run admissibility: never enabled inside a running study; the manifest records the switch, the stage and every bound; the workspace-mediation arms pin it off.

## Estimate (LLM-agent terms)

Size M. About six worker tasks: stimulus effector and request type; desired-state fields; feed support in both feeds (entity holder with cap, wrapping seek with the perceived-time end, gain, channels); credit window in the affect module; stage-M rule; records and manifest fields. Roughly 1,500 to 2,000 lines with tests, four PRs, every one with an Opus second review (welfare). About three to four agent-days, plus the validation boot. Stage L adds about one agent-day once its dependencies exist.
