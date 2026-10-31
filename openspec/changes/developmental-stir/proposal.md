## Why

In the developmental phase nothing the entity does changes its stimulus. Paper A.6 and A.7 describe a stir, specified and not built (§5.4): when the entity's own boredom or restlessness drive event leads an accessed broadcast, the entity stirs, and the maternal voice may answer after a short delay. A stir relieves restlessness at once, and the novelty of an answer can relieve boredom, credited to the entity's own response (A.4), so a stirring entity's boredom reads as controlled.

It matters now because of `welfare-indicator-response`. In the replayed eight-hour developmental test boot, boredom's indicator crossed at 2.7 awake hours and stayed over its bar. With the indicator response built, the net will rest such an entity, and when boredom recrosses over the fresh span it will preserve and freeze it for review. The study's seed gestates under that net. Without any instrumental relief, the expected outcome is a developmental phase that the net freezes, possibly more than once, before the seed matures.

The stir changes the seed's development, and therefore every branch of the study, which all start from that seed. It also breaks a standing invariant on purpose: the maternal channel is entity-independent (developmental-stimulus spec). Whether it is built before the study is the operator's decision; this change gives the design so the decision can be made on evidence.

## What Changes

- **Stir intent.** In the developmental phase, an accessed broadcast whose first non-organ member is the entity's own boredom or restlessness drive event yields an `intent.stir` instead of any other intent, when at least `Δ_st = 300 s` of entity time have passed since the last stir. At most one intent per broadcast, as now.
- **Answer.** The local stimulus source reads the stir and, with probability `p_st = 0.5` from a keyed draw on the seed and the stir's index, plays one maternal utterance from the unlocked repertoire after a delay uniform on `[2, 10]` s, mixed into the soundscape through the hearing band like any maternal speech. The heartbeat and the maternal state stay entity-independent.
- **Affect.** A stir counts as an intent other than rest, so it relieves restlessness; it is about a drive, so it gives no direct boredom relief (A.4). The stimulus source publishes a content-free `development.stir_answer` with its start and end; a boredom fall during an answer or within the response window `Δ_resp` after it is credited to the entity's own response.
- **Records.** Stirs and answers go to the research log, content-free, and into the welfare exposure record (stir count, answered count).
- **Offline check before any boot.** A harness with the real affect module, the real action selection and the local stimulus source's answer model, fed by the held-pool engine, estimates the stir rate, the answered share and boredom's deprivation share with and without the stir.

## Capabilities

### New Capabilities

### Modified Capabilities

- `action-selection`: the developmental stir intent.
- `developmental-stimulus`: the maternal channel stays entity-independent except for the answer to a stir; the answer rule.
- `affect`: a stir relieves restlessness; an answer's novelty is the entity's own response.
- `research-event-log`: stirs and answers are recorded.

## Impact

- Code: `kaine/workspace/action_selection.py` (`DefaultActionSelectionPolicy`), the development probe wiring, `kaine/modules/audition/maternal_voice.py` and the local stimulus source (answer queue), `kaine/modules/affect/` (stir as an intent, answer-window credit), `kaine/evaluation/observers/research_event_observer.py`, `config/kaine.toml` (`[perception_feed.stimulus_source.stir]`: `refractory_s`, `answer_probability`, `answer_delay_min_s`, `answer_delay_max_s`).
- Tests: the intent rule, the seeded answer, the credit window, the bounded loop, the offline harness.
- Docs: `docs/09-modules/` (action selection, affect), the developmental-phase chapter.
- Paper: §5.4 status, §7 and A.6, A.7 tense; the offline result in A.7.
- High-risk class (changes the entity's development): independent second review.
