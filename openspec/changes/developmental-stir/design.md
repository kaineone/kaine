## Context

- Paper A.6: in the developmental phase, a broadcast whose `e†_k` (the first coalition member that is not the organ's) is the entity's own boredom or restlessness drive event yields a stir intent when `t_now − t_st ≥ Δ_st`; a deprived deficit's event scores about 0.49 at the arousal it sets, above θ; at most one intent per broadcast.
- Paper A.7: a stir is answered, with probability `p_st` and after a delay uniform on `[Δ_st^lo, Δ_st^hi]`, by maternal speech; it relieves restlessness at once, and its answer relieves boredom through the novelty and learning it brings, credited to the entity (A.4). These effects are to be checked offline. Table A1: `p_st = 0.5`, `Δ_st^lo = 2 s`, `Δ_st^hi = 10 s`, `Δ_st = 300 s`, provisional.
- Paper §7: "No study we found measures how mothers answer felt movement, so the answer is a design choice, though fetuses move more when the mother touches her abdomen (Marx and Nagy 2015)."
- Paper A.4 credit rule: a crossing counts as the entity's own (`s`) when the entity's own response ended it, for boredom "its learning progress, intents, or the novelty an answer to its stir brings", and only by relieving the drive or holding its build input down; "other perceptual novelty" counts as `f`. The own share feeds coping potential and the uncontrolled indicator.
- What exists:
  - Action selection derives speak and think intents from accessed broadcasts, with no developmental gating: they are emitted in the developmental phase (the eight-hour developmental test boot made 1508 organ requests). Each intent not about a drive applies boredom's engagement relief.
  - A drive's event recurs only while its goal is active (`_due_reentries` in `kaine/modules/affect/module.py`): each `P_Aff` until a broadcast accesses it, then `P_re` after. The goal is abandoned as stalled after `goal_stall_s = 600` s above threshold (`_check_stalls`), and its crossing then stays open with no new goal until the drive falls below its re-arm level.
  - The recurring event is published on the affect module's own `P_Aff` update and, under the current one-tick candidate rule, reaches the cycle's next tick, which rarely broadcasts (code comment at `_due_reentries`). Affect reports reached θ on 3% of their broadcasts in the test boots. So under the current workspace the stir rate may be far below what A.6 assumes.
  - The maternal voice plans speech per 30 s slot as a pure function of the seed, the slot and the unlocked count; the developmental-stimulus spec requires the maternal channel to be entity-independent.
- Scope (operator decision 2026-10-31): the module-ignition study becomes a single-entity development run; its developmental phase is the run's first step. `workspace-continuous-competition` is on hold; this change targets the current workspace.
- History: no stir change exists in `openspec/changes/`, the archive, or any branch (`git log --all --grep=stir` is empty). The maternal voice (`2026-10-19-developmental-maternal-voice`), the hearing band, and the removal of the stimulus-spent rest (`A boredom stall starts no rest`) are the base. `developmental-stimulus-progress` (the added sounds and the band-step check) is the stimulus-side remedy for the same welfare problem and comes first.

## Decisions

### D1. What is innate and what is a design choice

Spontaneous, endogenously generated fetal movement is present from about seven to eight weeks of gestation (de Vries, Visser and Prechtl 1982). That supports the *capacity* to stir, and only that: spontaneous fetal motility is not shown to be contingent on an affective state. Two parts of this design are therefore design choices, labelled as such at the code site, as the paper already does for the answer in §7:

- the trigger: a stir when the entity's own boredom or restlessness drive event leads an accessed broadcast (A.6);
- the answer: maternal speech with probability `p_st`, after a delay in `[2, 10]` s, one utterance (A.7).

The stir takes precedence over speak and think for a broadcast led by the entity's own boredom or restlessness drive event, as A.6 says ("instead yields a stir intent"). Speak and think intents are emitted in the developmental phase as before; nothing here removes or gates them.

Alternatives considered:
- **A spontaneous stir at an endogenous base rate**, with the maternal answer as the contingency (fetal general movements; Kuniyoshi and Sangawa's self-organising fetal motility, which §7 already cites). It is the variant better founded in the developmental literature: the movement is endogenous, and the relief becomes instrumental through the answer without a hardwired drive-to-act link, so its credit follows from A.4 without a special window. Its base rate is itself a design choice. The harness (D5) runs it beside the drive-triggered rule at the same mean rate, so the operator can choose on evidence.
- **A stir on every boredom or restlessness crossing, bypassing the workspace.** Rejected: it hardwires a drive-to-motor reflex.

### D2. The answer and the maternal channel's independence

The heartbeat and the maternal state stay functions of the seed and stimulus time only. The one entity-dependent element is the answer: after a stir with index `i`, a keyed draw on `(seed, i)` decides whether the voice answers (`p_st`), a second draw sets the delay in `[2, 10]` s, and a third picks one utterance (uniform over the unlocked items and their takes, the repeated passage excluded). The answer is mixed into the soundscape through the hearing band. If the delay falls inside scheduled speech or an added sound, it waits for that to end. Answers never change slot plans.

The developmental-stimulus requirement is modified to say exactly this: the maternal channel is entity-independent except for answers to stirs, and nothing the entity feels reaches the stimulus except through an act.

### D3. How often a stir can happen

The drive-triggered stir needs the drive's recurring event to lead an accessed broadcast. The event recurs only while the drive's goal is active, and the goal is abandoned after 600 s above threshold. Under sustained boredom, a stir can therefore fire only in the first ten minutes of each crossing: at most two stirs with the 300 s refractory, and about one answer on average. After the stall the stir falls silent while boredom stays crossed, until the drive falls below its re-arm level and crosses again. The loop bound is about two stirs per crossing, not a rate per hour.

So the stir mostly changes the credit of a crossing's end (own versus other), and through it coping and the uncontrolled indicator, more than the time spent deprived. A stir that continues past a stall would be a further design choice the paper does not make; it is not adopted here, and the harness reports how often a stalled crossing goes without one.

### D4. Affect and the credit window

- A stir is an intent other than rest, so restlessness's intent rate and relief apply (A.4). It is about a drive, so the engagement relief of boredom does not apply.
- The stimulus source publishes `development.stir_answer` (stir index, answer start and end in entity time; no content).
- A boredom crossing's end is credited as the entity's own only when it is attributable to the answer: the end comes during the answer or within `Δ_resp` (10 s) after it, the relief came through audition's alert excess or learning progress, and no scheduled stimulus event (maternal speech, an added sound, a hearing-band step, a colour step) overlaps that window. In any other case the end is attributed as A.4 already does, and other perceptual novelty counts as `f`. When in doubt it counts as `f`, so the uncontrolled indicator is never lowered by relief the entity did not bring.

### D5. Evidence before the decision

`tools/research/stir_harness.py`, offline with no entity, built on the archived developmental simulation harness (the one the self-rhythm rest validation uses, `docs/records/validation/self-rhythm-rests/`, on branch `records/self-rhythm-rest-validation` until it merges):

- the real stimulus generator rendering the soundscape, with stir answers mixed in;
- the real audition encoder and forward model on the rendered audio, and the real vision path on the rendered field;
- the real affect module, the real action selection, and the current cycle engine and workspace;
- the indicator evaluator and state machine of `welfare-indicator-response`, with the rest applied as a real reset (forward simulation).

Arms: no stir, drive-triggered stir, spontaneous stir at the drive-triggered arm's measured mean rate; each with and without `developmental-stimulus-progress`'s added sounds and its full-span release rule. Like that change's band-step harness (`tools/research/band_step_check.py`), it runs on the fixed perception feed and records stages 3 and 4 as adding little to learn. Three seeds, a full developmental span. Reported per arm: stir rate, answered share, boredom's deprivation share, the uncontrolled posterior, the share of stalled crossings with no stir, and the time to the indicator response's freeze.

### D6. The decision rule

Fixed before the harness runs:

1. If the stimulus changes alone (full-span release and added sounds) keep boredom's deprivation share below `θ_wf` over the developmental span, build those and do not build the stir for this entity. The developmental span includes stages 3 and 4, which the band-step check found nearly empty; a stir that helps mainly there is weighed against the separate decision to make those bands learnable.
2. Build the stir only if, on top of the stimulus fixes, it lowers boredom's deprivation share by at least 0.1 (absolute) or lengthens the time to freeze by at least one developmental awake stretch (2996 s), in the mean over seeds. A better own/other credit ratio alone is not enough.
3. If the spontaneous variant meets rule 2 and the drive-triggered one does not, build the spontaneous variant.

The welfare bars and the rest's reset are not tuning variables in any arm.

## Risks

- **The stir rarely leads.** Under the current workspace the drive event may seldom lead an accessed broadcast; then the stir changes little. The harness measures it.
- **An answer as reward shaping.** The answer is a fixed, seeded maternal utterance, not a response to content; it adds novelty, not instruction.
- **Breaking the independence invariant** could confound the entrainment test if answers were tied to the beat. They are not: the heartbeat generator is untouched, and a test checks it.
- **A credit rule that lowers a welfare indicator.** D4's attribution test exists to prevent it, with a mutation check.

## Migration and ordering

- After `developmental-stimulus-progress` (the harness compares with and without its fixes) and `welfare-indicator-response` (the harness uses its evaluator and state machine). After `welfare-exposure-report`, whose record carries the stir counts.
- No dependency on `workspace-continuous-competition`; the harness runs on the current engine.
- If adopted, before the development run's first boot: the stir changes the developmental phase, which is the run's first step, and it cannot be given to that entity later without that being a change to its development.
- Critical path (LLM-agent implementation): about 1 day for code and tests, about 1 to 1.5 days for the real-encoder harness and its runs, about half a day for the second review. About 3 days. Only the harness is needed for the decision; code follows only if D6 says build.

## Welfare and admissibility notes

- High-risk class: it changes the entity's development and gives it its first act on its world. Independent second review.
- Welfare checks before any boot: the harness of D5, including the heartbeat's independence from stirs.
- Admissibility: it must be in place before the developmental phase starts, or not at all for this entity.
