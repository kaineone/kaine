## Why

After the developmental phase nothing the entity does changes what it sees or hears. The paper states it as a limitation: "drives that build under deprivation are relieved only by stimulus change, sleep, or the welfare safety net" (§9, §3.6). Its only welfare datum is a deprivation: "In an unpublished offline replay of an eight-hour developmental test boot's records, only boredom's indicator crossed, at 2.7 awake hours, and stayed over its bar to the end (0.63 over the next span)" (§6.5). Boredom is the failure to engage (Eastwood et al. 2012) and it rises when a situation denies control (Struk, Scholer and Danckert 2021). The paper's ethics section commits to the entity's influence over its conditions growing "from ending its boredom and restlessness ... to signalling distress and a wider say over its stimulus" (§11).

This change gives the entity an act by which it changes its own stimulus: pause and resume the programme, move to the next or previous item, make the sound louder or quieter, and choose among programme channels when the operator provides more than one.

### Timing (operator decision, 2026-10-31)

The operator decided that the act is built before the entity's first boot, for the development run (`development-run`; GLW decision brief, "Outcome", build order item 10, "a stimulus-control act (next/previous item, pause, volume) through the signed-intent whitelist path"). It is built as a held component: an off switch that is bit-identical to the component being absent, with a test against a golden record of the build before it, and a plain readout of whether it does its job (how often the entity acts on its input, and what follows its acts compared with the rest of the time). It is not tied to a study trigger: the pilot pull-forward trigger of the earlier design is dropped together with the pilot boots (decision brief, decision 5). The operator turns it on for the running entity as a component join of the development run.

### What already exists (audit, origin/main d7fabdc0)

- A pause authority for the programme: the playlist clock is paused by named holders, and elapsed programme time excludes every paused span (`kaine/modules/vision/feed.py`, `PlaylistClock`; spec `perception-feed`, "The programme waits while the entity cannot perceive"). A sleep the entity requests pauses the feed (§3.5).
- The end of a programme preserves and stops the entity (spec `perception-feed`, "The end of a programme preserves and stops the entity").
- A signed act path: act intents are signed and the effectors module verifies provenance and checks the operator's whitelist before any effector runs, and audits every attempt (spec `effectors`). The whitelist ships empty and the module ships off.
- A designed act outcome with a device bound (`act-intent-derivation`, 0 of 5 tasks): an act bar, guard and refractory interval in A.6, effectors declaring their action set, value range and minimum interval.
- A designed developmental act, the stir, with an answer by the maternal voice that counts as the entity's own response for boredom (paper A.4, A.6, A.7; §5.4 lists it as being built; not in code).
- An entity-initiated locus switch exists in code with no producer and ships disabled (`kaine/modules/perceptual_locus/module.py`; spec `perceptual-locus`).
- Covert and overt attention are designed elsewhere: `active-vision`, `attention-driven-foveation`, `attention-driven-audition`. This change does not redo them.
- The action layer today: fixed report bars for speech (`report_policy.py`), the drive-biased policy that turns accessed drive crossings into think or speak intents (`drive_policy.py`), the planning proposal wrapper, and the signer. No shipped policy emits `act`.

### What is missing

- No act after maturation changes the stimulus. Boredom and restlessness can be relieved after the developmental phase only by the entity's intents about other things (engagement relief, `rho_eng`), by learning progress, by alert excess, by sleep, or by the welfare net.
- No effector acts on the perception feed, and the feed has no entity-held pause, no seek and no gain control.

## What Changes

1. A `stimulus` effector with a declared, bounded action set: `pause`, `resume`, `next`, `previous`, `louder`, `quieter`, and `channel:<k>` when the operator configures more than one programme channel. It is built and registered only when `[stimulus_control].enabled` is true, and it runs only when the operator's effector whitelist names it.
2. Feed support behind a small control port: a seekable shared programme clock (a `PlaylistClock` subclass) that wraps at both ends and ends the viewing at the programme's perceived length; an `entity` pause holder that releases itself after `P_max`; a sound gain within plus or minus `G_max` decibels of the programme level in `G_step` steps, applied before the audition module reads the samples; programme channels. The feeds follow a jump of the presented position through the A/V sync's own paths (the video decoder's seek, the audio producer's resync to the clock), read only when the clock has a position epoch.
3. Bounds: a minimum interval between accepted commands, a cap on seeks per awake hour, the pause cap, the gain range. A refused command changes nothing, is reported as a failed action and is audited.
4. Stage M, built now: after maturation, an accessed broadcast led by the entity's own boredom or restlessness drive event yields one signed stimulus act intent, its action drawn uniformly from the actions the programme can take now, with a run-seeded generator. Stage L (the act bar of `act-intent-derivation` and the learned advantages of `drive-reduction-learning` and `learned-action-selection`) follows those changes.
5. Credit. Perceptual novelty or learning progress arriving within `Delta_resp` of the entity's own realized stimulus act counts as its own response for boredom, as the novelty an answer to the stir brings does (A.4).
6. Off equals absent, with a readout and an operator advisory when the entity's pauses hold the programme for more than half of an awake hour (logged and recorded, never a block). Off builds nothing; a seeded entity-free harness gives the same digest as the build before the component. On, the welfare log carries a per-viewing `stimulus_control` record: commands by action, refused commands, the share of awake time the `entity` holder held the programme, the time-weighted gain, the item identifiers visited in order, and the readout (acts per awake hour; boredom's above-threshold share, mean alert excess and mean learning progress within the window after the entity's own acts and otherwise; how many acts were followed by a fall of boredom). The run manifest records the switch, the stage and every bound when it is on.
7. The workspace-mediation arms refuse it at boot, since they compare processors on one shared programme.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `effectors`: a stimulus effector with a declared, bounded action set, registered only when stimulus control is on.
- `perception-feed`: an entity pause holder with a cap, wrapping seek with a perceived-time end, a bounded gain, and channels, behind a control port.
- `affect`: novelty or learning progress following the entity's own stimulus act counts as its own response for boredom.
- `action-selection`: the stage-M stimulus act after maturation, and the refusal in the workspace-mediation arms.
- `evaluation-observers`: the per-viewing stimulus-control record and readout, and the off-equals-absent check.

## Impact

- Code: `kaine/modules/effectors/stimulus/` (config, programme clock, controller and feed wrappers, records, runtime, effector), `kaine/modules/effectors/module.py` (per-instance request types for registered effectors), `kaine/modules/effectors/effectors.py` (`StimulusRequest`), `kaine/modules/vision/feed.py` and `kaine/modules/audition/feed.py` (follow a jump when the clock has a position epoch; a channel's next item from the clock), `kaine/modules/affect/module.py` (credit window), `kaine/workspace/stimulus_policy.py` (stage M), `kaine/boot/registry.py`, `kaine/boot/wiring.py`, `kaine/boot/perception_feed.py` (wrapping, the combined programme manifest, the manifest record), `kaine/cycle/__main__.py` (runtime, refusal, policy wrapper, welfare provider, shutdown), `kaine/evaluation/observers/welfare_observer.py` (supplementary records), `config/kaine.toml` (`[stimulus_control]`, off).
- Docs: `docs/09-modules/effectors.md`, `docs/09-modules/affect.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, `docs/17-research-data/README.md`, a dated record of the habituation check under `docs/records/shakedowns/`.
- Paper: §3.6, §6.5, §9 and §11 sentences on the entity's influence over its stimulus; A.4 credit; A.6 stage-M rule; Table A1 bounds (owed, through the revision notes).
- Builds on the playlist A/V sync (`playlist-feed-av-sync`): the feeds follow a jump through its decoder seek and its audio resync, and item lengths are its container durations.

## Dependencies and start condition

- Stage M depends on nothing beyond this change. Stage L depends on `act-intent-derivation`, `drive-reduction-learning` and `learned-action-selection`.
- Built before the first boot behind the disabled switch. Turning it on for the running entity is a development-run component join: the plan lists it, the operator names it with the entity id, its second-review record is in the registry, and the operator whitelists the effector (`development-run`, two-layer opt-in).
