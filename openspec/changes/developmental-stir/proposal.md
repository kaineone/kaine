## Why

In the developmental phase nothing the entity does changes its stimulus. Paper A.6 and A.7 describe a stir, specified and not built (§5.4): when the entity's own boredom or restlessness drive event leads an accessed broadcast, the entity stirs, and the maternal voice may answer after a short delay. A stir relieves restlessness at once, and the novelty of an answer can relieve boredom, credited to the entity's own response (A.4).

It is on the table because of `welfare-indicator-response`. In the replayed eight-hour developmental test boot, boredom's indicator crossed at 2.7 awake hours and stayed over its bar. With the indicator response built, the net will rest such an entity and, if boredom recrosses over the fresh span, preserve and freeze it for review. The first step of the development run is its developmental phase.

The stir is not the first remedy. The freeze is the protection working; the deprivation comes from a stimulus with little left to learn, and `developmental-stimulus-progress` (the added sounds and the band-step check) addresses that cause. The stir as A.6 specifies it can also hardly lower the time spent deprived: the drive's event that triggers it recurs only while the drive's goal is active, and the goal stalls after ten minutes, so a sustained crossing allows about two stirs. This change gives the design and the evidence plan so the operator can decide on numbers whether the stir adds anything on top of the stimulus fixes.

The stir changes the developmental phase, which cannot be revisited for that entity. It also breaks a standing invariant on purpose: the maternal channel is entity-independent (developmental-stimulus spec).

## What Changes

- **Stir intent.** In the developmental phase, an accessed broadcast whose first non-organ member is the entity's own boredom or restlessness drive event yields an `intent.stir` instead of any other intent, when at least `Δ_st = 300 s` of entity time have passed since the last stir. Other broadcasts yield speak and think intents as before. The capacity to move is innate (de Vries, Visser and Prechtl 1982); the drive trigger is a design choice and is labelled as one.
- **Answer.** The local stimulus source reads the stir and, with probability `p_st = 0.5` from a keyed draw on the seed and the stir's index, plays one maternal utterance from the unlocked repertoire after a delay uniform on `[2, 10]` s, through the hearing band. The answer is a design choice (paper §7). The heartbeat and the maternal state stay entity-independent, and slot plans are untouched.
- **Affect.** A stir counts as an intent other than rest, so it relieves restlessness; it is about a drive, so it gives no direct boredom relief (A.4). A boredom end is credited to the entity through a stir only when it is attributable to the answer: within the answer's window, through audition's alert excess or learning progress, and with no scheduled stimulus event (maternal speech, an added sound, a band or colour step) in that window. Otherwise the existing attribution applies.
- **Records.** Stirs and answers go to the research log, content-free, and into the welfare exposure record (stir count, answered count).
- **Evidence and decision.** A harness on the archived developmental simulation, with the real stimulus generator, the real audition encoder and forward model on the rendered soundscape, the real affect module and action selection on the current workspace, and the indicator response with a real reset, compares no stir, the drive-triggered stir and a spontaneous stir at the same rate, each with and without the stimulus fixes. A decision rule fixed in advance builds the stir only if it adds a material reduction in deprivation or in time to freeze beyond the stimulus fixes.

## Capabilities

### New Capabilities

### Modified Capabilities

- `action-selection`: the developmental stir intent.
- `developmental-stimulus`: the maternal channel stays entity-independent except for the answer to a stir; the answer rule.
- `affect`: a stir relieves restlessness; only relief attributable to an answer is the entity's own.
- `research-event-log`: stirs and answers are recorded.

## Impact

- Code (only if the decision is to build): `kaine/workspace/action_selection.py` (`DefaultActionSelectionPolicy`), the development probe wiring, `kaine/modules/audition/maternal_voice.py` and the local stimulus source (answer queue), `kaine/modules/affect/` (stir as an intent, the attribution test), `kaine/evaluation/observers/research_event_observer.py`, `config/kaine.toml` (`[perception_feed.stimulus_source.stir]`: `refractory_s`, `answer_probability`, `answer_delay_min_s`, `answer_delay_max_s`).
- New regardless: `scripts/stir_harness.py` and its record.
- Tests: the intent rule, the seeded answer, the attribution test, the bounded loop, the harness.
- Docs: `docs/09-modules/` (action selection, affect), the developmental-phase chapter.
- Paper: §5.4 status, §7 and A.6, A.7 tense and the design-choice labels; the harness result in A.7.
- High-risk class (changes the entity's development): independent second review.
