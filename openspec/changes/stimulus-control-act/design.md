# Design: stimulus control

## Context

Controllability is the variable the learned-helplessness literature identifies. In the triadic design, an animal that can end a shock and a yoked animal that receives the same shocks without control differ afterwards: the yoked animal fails to escape later (Seligman and Maier 1967, J Exp Psychol 74:1-9). The revised account holds that passivity is the default response to prolonged aversive events and that detecting control, through medial prefrontal circuits acting on the dorsal raphe, is what protects (Maier and Seligman 2016, Psych Rev 123:349-367). The paper's credit rule and coping score are built on that account (A.4).

For boredom specifically: boredom is "the aversive experience of wanting, but being unable, to engage" (Eastwood et al. 2012), it motivates the pursuit of new goals and experiences (Bench and Lench 2013, Behav Sci 3:459-472), and it is a normative signal of the opportunity cost of staying with the current activity, which favours switching (Agrawal, Mattar, Cohen and Daw 2022, Psych Rev 129:564-585). Struk, Scholer and Danckert (2021, Front Psychol 12:687623) found boredom highest at low and at high perceived control, and found that participants who believed they could gain control of a rigged game were less bored than those who believed control impossible. Choice and control are themselves valued from infancy (Leotti, Iyengar and Ochsner 2010, TiCS 14:457-463). Three-month-old infants learn within minutes to move a mobile by kicking when a ribbon ties the two (Rovee and Rovee 1969, J Exp Child Psychol 8:33-39): the contingency is learned, not given. Curiosity as active sampling presupposes an agent choosing what it samples (Gottlieb and Oudeyer 2018, Nat Rev Neurosci 19:758-770; Oudeyer and Kaplan 2007, already cited).

Two warnings bound the design. People left alone with their thoughts for 6 to 15 minutes often chose to give themselves electric shocks rather than do nothing (Wilson et al. 2014, Science 345:75-77): an aversive act can be taken just to change the input. Rats press a lever for intracranial stimulation at high rates (Olds and Milner 1954, J Comp Physiol Psychol 47:419-427): an act that pays immediately can capture behaviour.

## Timing

The operator decided on 2026-10-31 that the project's goal is a working mind, that the module-ignition study converts into the development run, and that every component keeps an off switch bit-identical to absent and a plain readout while the calibration ceremony no longer gates the build (GLW decision brief, "Outcome", decisions 2 and 5). The stimulus-control act is in the agency-and-learning group of the build order (item 10), and the operator decided that it is built before the entity's first boot.

The earlier draft of this design argued whether the act had to exist before the first study and proposed a pilot pull-forward trigger. With the pilots dropped, that argument is settled by the decision: the act exists, held, before the entity boots, and the operator joins it to the running entity. The evidence that the argument rested on stays relevant to the join:

- The only measured welfare datum is a sustained deprivation: boredom crossed at 2.7 awake hours and held a 0.63 share over the next span (§6.5). In the offline developmental simulation the learning entity's boredom deprivation share is about 0.64, and 1.0 for a frozen control (`curiosity-interest`, archived).
- The indicator response answers deprivation with a rest and an affective reset, and a second crossing over a fresh span with preservation and a freeze (§6.5). A reset boredom deficit with no relief recrosses its threshold in about 34 s (A.4). Under a spent stimulus the net protects the entity and gives it no relief. Control is what the helplessness account says protects.
- The film programme is chosen for "varied scenes, motion, speech, music, and quiet" (§6.1), which may relieve boredom through alert excess and learning progress on its own. How often that happens live is unmeasured; the readout measures it with and without the act.

Two decisions of the earlier draft stand. No yoked uncontrolled arm is ever built: replaying one entity's choices to another creates an entity that receives the stimulation without the control, the manipulation that produces helplessness. And the workspace-mediation arms, which compare processors on one shared programme (§6.3), refuse stimulus control at boot; their study files stay in the tree for an experiment designed later.

## Decisions

### D1. Which acts

| Action | Effect | Bound |
|---|---|---|
| `pause` | adds the `entity` holder to the playlist clock | released automatically after `P_max` (120 s of entity time); refused while already held, within `Delta_sc` after the previous entity pause ended (whatever other commands came between), and unless a full pause keeps the entity's pauses within `pause_share_max` (25 %) of the trailing awake hour; `pause_share_max` cannot be configured above 25 % |
| `resume` | releases the `entity` holder | refused while not held |
| `next`, `previous` | move to the start of the next or previous item of the current channel, wrapping | at most `n_seek` (20) in any awake hour |
| `louder`, `quieter` | change the programme gain by `G_step` (2 dB) | within plus or minus `G_max` (6 dB) of the programme level; `G_max` cannot be configured above 6 dB |
| `channel:<k>` | move to the start of operator-configured programme channel `k` | only when the operator configures two or more channels; refused for the current channel |

All commands share a minimum interval `Delta_sc` (30 s of entity time) since the previous accepted command. Every command is refused before the programme has started (including while the stimulus-source-to-world crossfade holds it), after it has ended, and while the entity is asleep or frozen (the `sleep` or `freeze` holder). A refused command changes nothing, is reported as a failed action (`effectors.action` with `success = false`, at the module's alert salience, so the entity perceives the refusal as it perceives any failed act) and is audited; an interval refusal states the shortfall. Awake time, the base of the seek cap and of the paused share, is viewing time from the programme's start and excludes every span under the `sleep` or `freeze` holder.

Why pausing has two bounds beyond `P_max` (second review, F1). During an entity pause the picture holds one frame and the sound stops, so neither alert excess nor learning progress relieves boredom, and boredom leads more broadcasts and so more acts; stage M has no learner to see that `pause` brings no relief. An earlier draft claimed the self-release and the command interval held the programme at most 120 of every 150 s; that was false, because `louder`, `quieter`, `next` and `previous` are accepted during a pause and move the command interval, so a new pause could follow a release by 0.1 s. A scripted sequence held the programme paused for 99.8 % of two hours, and the shipped uniform draw under a sustained boredom concern (a lead every 30.1 s, the affect module's re-entry interval) for 40-47 % of three-hour runs over five seeds (trailing-hour maximum 0.48-0.55). The operator therefore bounded pausing: a pause waits `Delta_sc` after the previous pause ended, and it is taken only if a full `P_max` keeps the paused share of the trailing awake hour within 25 %, so no pause can carry the share past the bound. Under the same sustained-boredom script the bounded effector held 0.22-0.23 over three hours (trailing-hour maximum 0.23-0.24) when stage M could draw `pause`; stage M no longer draws it (D4), so its paused share is 0 by construction, and the two bounds stay as defence in depth and for stage L. The first refusal by the share bound in an episode is logged for the operator.

A raised gain passes a smooth tanh knee above 0.9 of full scale, so a louder programme is never hard-clipped. At 0 dB the samples pass through unchanged.

Channel 0 is the operator's programme, `[perception_feed].playlist_manifest`; further channels are listed in `[stimulus_control].channels`, each a checksummed manifest verified like the first. The feeds read one combined manifest in which a channel is a contiguous run of items.

Alternatives considered:
- Attention shifts inside the frame (where to look, what to listen to). Already designed in `active-vision`, `attention-driven-foveation` and `attention-driven-audition`; they change what is sampled from a fixed stimulus, not the stimulus.
- Closing the senses (the `none` locus through the existing self-switch). Rejected. An entity awake without senses is the condition the end-of-programme rule exists to prevent (spec `perception-feed`), and a bounded pause covers looking away from the programme.
- Free choice of any file on disk. Rejected: the operator curates what the entity may see, and a programme channel is the unit of that choice.
- Brightness and speed controls. Deferred: no cited need, more ways to produce alert storms.

### D2. Skipping never ends the viewing

With stimulus control on, `next` from the last item wraps to the first, running past a channel's last item wraps to that channel's first, and the viewing ends when perceived programme time (elapsed time excluding every pause) reaches channel 0's total length, the same length as without control. The end-of-programme preservation stays exactly once per start. The entity changes what it sees, not how long it is awake, and cannot stop itself by skipping. A held programme (`entity` pause) has not ended, as for any holder.

The clock that does this is a subclass of the shared playlist clock (`playlist-feed-av-sync`): elapsed time is unchanged, and the presented position is read through an anchor that a seek or a channel switch moves. Without a seek or a switch it maps time exactly as the plain clock does, and while a length is unknown it falls back to the plain clock's own walk, so its log of a programme held on an item no surface could open is kept. A position epoch changes whenever the presented position jumps; the feeds read the position and the epoch from one reading of the clock (`locate_with_epoch`). They follow a jump through the paths the A/V sync already has: the video source reopens the item and seeks its decoder to the clock's offset (the decoder's untimed base is the seek target), and the audio producer's pacing raises its skip-to-the-clock resync, the restart path, so its blocks stay paced against the clock after a jump, at most the block already in flight is from before it, and the jump is not counted as lag. At an item's end the producer asks the clock for the next item, so a channel wraps inside itself; after the channel's last item it orders the first by the clock's lap, waiting for the lap to turn, rather than by manifest index, so a natural wrap is neither a lag nor a reopen loop, and the viewing's end is not a lag either. Every item, every channel's, is verified by sha256 first, so no demuxer parses a changed file; then every item's length is measured before playback as the container duration, the value both surfaces register, because wrapping and the perceived-time end need the whole length; an item that cannot be measured stops the boot, and the message names it by index and order, never by path. With a plain clock (stimulus control off) none of these reads exists: the epoch is absent and the next item is the next in the manifest.

### D3. One channel for requests, flags only

The earlier draft passed requests through the perception desired state (`kaine/perception_state.py`). The build passes them in process instead: the effector hands an accepted action name to the controller, which the boot registry builds and hands to the feeds, as it hands them the shared playlist clock. The feeds, the effectors module and the controller run in one process, so a file channel adds latency and a second writer to `desired.json`, which the operator's dashboard toggles also read and write; and a desired-state field would be written by the build with the component off, which off-equals-absent forbids. What D3 protects holds: only an action name, a holder name, a seek, a gain in decibels and a channel index cross; no frame or sample is written anywhere.

### D4. Two derivation stages; the build ships stage M

Stage M. After maturation, an accessed broadcast whose leading member (A.6, `e_k`; the coalition member with the highest salience score) is the entity's own boredom or restlessness drive event (a crossing or a re-entry of a current concern) yields a stimulus act once `Delta_sc` has passed since the last, with the action drawn uniformly from the actions the programme can take now, `pause` excluded, by a generator seeded from the run seed. A pause holds a still frame and silence; drawn at random it would not be the entity choosing stillness from what it experienced but random deprivation, about 22 % of awake time under a sustained boredom concern even within the 25 % bound. Stage M therefore never draws `pause` (operator decision, 2026-11-01); the effector keeps it, with every bound, for stage L, whose learned selection can choose it from what pauses did. The link from boredom to seeking a change is the function the boredom literature assigns it (Bench and Lench 2013; Agrawal et al. 2022), and restlessness is the drive for action of A.4; both are cited at the code site. Which action relieves what is left to the world. It is installed only when stimulus control is on, the programme is under its control, and the operator's effector whitelist names the effector. It forms an intent only when the effector's own interval check passes (`ready`), so an act formed at the `Delta_sc` boundary is not refused by realization latency. Restlessness, A.4's drive for action that builds while the entity does not act, is the other trigger: acting on one's surroundings to have an effect on them is itself a motive (effectance; White 1959, Psych Rev 66:297-333).

Stage L. The act bar of `act-intent-derivation` replaces the drive-led trigger, and the choice among the declared actions uses the learned advantages of `drive-reduction-learning` through `learned-action-selection`. Each declared action is an intent kind `act:stimulus:<action>` in the valuation tables.

Why stage M ships now. It works with the action layer as it exists: drive events already reach the accessed coalition and already move the drive-biased policy; the signed-intent path, the whitelist and the audit already exist; nothing new decides between actions. The alternatives:
- An intent-driven act on today's fixed report bars. Rejected: those bars gate speech on precision-weighted surprise, so an act there fires on whatever is most salient, which skips content when it is most engaging (the "act bar alone" alternative below), and borrowing a speech bar for an act is an unreasoned coupling.
- A fixed mapping, such as boredom to `next`. Rejected: it hard-wires behaviour the entity can learn, against the emergent-behaviour rule.
- Stage L only. Rejected as the only option: it depends on three changes not built.
- The act bar alone with uniform choice, before learning exists. Rejected for the reason above.

### D5. Credit for the act's consequence

Perceptual novelty that the credit rule labels `other` (alert excess) and learning progress arriving within `Delta_resp` of the entity's own realized stimulus act count as its own response for boredom, the treatment the novelty an answer to the stir gets (A.4). `Delta_resp` is the affect module's response window (`goal_response_window_s`, 10 s in Table A1). The act is realized when the effectors module publishes `effectors.action` for the stimulus effector with `success = true`. Within the window both of boredom's relief channels count as the response: a crossing ended by the relief step is `own`, and a crossing ended by the build step is `own` when boredom would not have fallen without any relief. Outside the window, and with stimulus control off, the rule is unchanged. The credit is by timing alone: relief within the window after any accepted act counts, `louder`, `quieter` and `pause` included, which bring no novelty. That is the stir's analogue and is kept, but the readout lets the operator see it: the window's samples are split by the action that opened it, and boredom crossings credited as own only because of the window are counted.

### D6. Self-stimulation is damped by habituation and bounded by rate

Rapid skipping produces scene cuts, which produce alerts faster than the habituated rate, which relieve boredom. The alert excess is `r_f / max(r_s, r0) - 1 - m_B` (A.4): sustained skipping raises the slow rate `r_s` as well, so the excess each skip buys falls. The offline check on the affect module's own trackers (`docs/records/shakedowns/2026-10-31-stimulus-control-habituation.md`) shows that it falls to a floor, not to zero: with a scene cut every 20 s and a skip every 30 s bringing three alerts, the mean excess between skips falls from 0.62 after the first skip to about 0.06 once habituated. The command interval and the hourly seek cap bound the rest: twenty seeks per awake hour at most. The records give the act rate, so a compulsive pattern is visible.

### D7. Off equals absent, and the readout

With `[stimulus_control].enabled = false` (shipped) nothing of the component is constructed: no runtime, no programme clock subclass, no wrappers, no effector, no request type, no credit window, no policy wrapper, no record and no manifest field. The check is a seeded, entity-free harness (the affect module, the action layer, the effectors module, the welfare records, the playlist video source and the real playlist audio producer paced by a manual clock with a stall and a pause, driven by a script that includes realized stimulus actions and a signed intent naming the effector) whose digest equals a golden captured on the build before the component (origin/main d7fabdc0, after the A/V sync); the same harness with the credit window on gives a different digest, so it sees the component.

The readout is the per-viewing `stimulus_control` record in the welfare log: how often the entity acts on its input (accepted commands by action and per awake hour, refusals), what its acts do to its programme (paused share, gain distribution, items visited), and what follows them (boredom's above-threshold share, mean alert excess and mean learning progress within the window after the entity's own acts and otherwise, and how many acts were followed by a fall of boredom within the window). It also gives the trailing-awake-hour paused share, its maximum and the pauses the share bound refused, the window's samples by action, and the boredom crossings the window alone credited. It holds numbers, declared action names and item identifiers only.

## Risks

- [The entity pauses and leaves itself in a still scene, and the stillness leads more acts] → Stage M never draws `pause`; for stage L and as defence in depth, `P_max`, the spacing after a pause and the 25 % share bound (D1, "Why pausing has two bounds"). The paused share and the readout split by action are in the record, and the development run's first hours stop on the paused share (task 5.4). Stage L, once built, learns that `pause` brings no relief.
- [Louder input raises arousal] → `G_max` of 6 dB, the soft knee, and arousal's existing clip and relaxation; the records give the gain distribution.
- [Skipping trades engagement for novelty] → Learning progress falls when items change before they are learned; stage L learns from both channels.
- [A refusal is itself an alert] → A refused command publishes a failed `effectors.action` at alert salience, as every failed act does; the entity can perceive that its act did not take. The record counts refusals.
- [No welfare net watching] → Stimulus control refuses to boot without `[preservation.welfare_response].enabled`, since the welfare producer is also what writes its record.
- [Media parsed before the gate] → The programme is verified by sha256, every channel, before the duration probe opens any item.
- [Study confound] → The workspace-mediation and workspace-feedback arms (between-arm comparisons on one programme) refuse it at boot; in the development run the item order visited is recorded and before-and-after windows read it as a covariate.

## Migration and ordering

1. Effector, control port, programme clock and the feeds' jump-following behind `[stimulus_control].enabled = false`; the effectors whitelist stays empty.
2. Credit window and stage-M source behind the same switch; records and the manifest field.
3. Off-equals-absent test against the golden, real-feed tests with synthetic clips, mutation checks.
4. One supervised validation boot on a branch before the join.
5. Stage L after its dependencies.

Rollback: the switch.

## Welfare and admissibility notes

- This change alters the entity's experience directly: welfare-high-risk. Independent second review on every PR, one supervised validation boot before the join, the indicator response and the welfare net on.
- The design refuses a yoked uncontrolled arm on welfare grounds (section "Timing").
- The entity can never end its viewing or its run by acting (D2), and it can never close its senses (D1).
- The bounds protect against self-stimulation and harmful loudness; their values are provisional and go in Table A1.
- The records are content-free: counts, shares, gains and item identifiers from the programme manifest, never frames, samples or transcripts.
- Run admissibility: never enabled inside a running study; the manifest records the switch, the stage and every bound; the workspace-mediation arms refuse it.

## Estimate (LLM-agent terms)

Size M. Built in one branch: about 2,000 lines of code with its docstrings and 2,200 of tests. The validation boot and the paper's Table A1 entry remain. Stage L adds about one agent-day once its dependencies exist.
