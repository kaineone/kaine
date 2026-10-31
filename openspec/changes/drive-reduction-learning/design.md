# Design: drive-reduction learning

## Context

Drive-reduction theory treats the fall of a need as the reinforcer (Hull 1943, cited in §3.5). Keramati and Gutkin (2014, eLife 3:e04811) give the computational form the paper already cites: the reward of an outcome is the reduction it brings in a drive function, the distance of the internal state from its set point, so the same outcome is worth more when the need is greater, and maximizing that reward keeps the internal state near its set point. The reward prediction error of midbrain dopamine neurons is the learning signal of this family of models (Schultz, Dayan and Montague 1997, Science 275:1593-1599). Outcome value in animals depends on the current motivational state, and an action's value is relearned when that state changes (incentive learning; Dickinson and Balleine 1994, Animal Learning & Behavior 22:1-18). The value-based decision framework separates the learned outcome expectation from the state-dependent valuation (Rangel, Camerer and Montague 2008, Nat Rev Neurosci 9:545-556).

KAINE already computes the three ingredients: deficits with set point 0, the relief channels, and a credit rule that labels a relief as the entity's own. What it lacks is the learner.

The cognitive-architecture frame asks for the same thing. ACT-R learns the utility of each production from the rewards that follow it (Anderson et al. 2004, Psych Rev 111:1036-1060), and Soar-RL learns numeric preferences for operators (Nason and Laird 2005, Cognitive Systems Research 6:51-59).

## Decisions

### D1. A held module, not a part of the affect module or the action layer

The learner is a new held module, `valuation`, after the striatal and midbrain valuation circuits (Schultz et al. 1997; Rangel et al. 2008). It reads `affect.state` and `action_selection.out` from the bus and publishes its own events.

Alternatives considered:
- Inside the affect module, generalizing the goal likelihood `L`. Rejected. The affect module is 1975 lines and the precision core of the competition; the module-addition study needs the learner switchable by `[modules]` like every other held capability, and the paper's claim "each predictive module adds a new source of prediction error" (§4) fits a module of its own. `L` stays as the appraisal's obstruction input.
- Inside the action layer (`kaine/workspace/`). Rejected. The action layer is called after each broadcast and must stay fast and stateless apart from its guards; a persisted learner with bus consumers belongs on the module side of the import contract.
- Inside the planning module, as a deficit factor. Partly adopted in `multi-step-planning`, which reads this module's values. The planning module is held, slower and runs on its own model; the first-configuration action layer needs relief estimates without it.

### D2. Learn an outcome model per drive, compute value from the current state

The module learns `Q_d(c, k)`, the expected relief of deficit `d` within the window after intent kind `k` in context `c`. Value is computed when asked, from the current deficits:

```
V(c, k) = F(D) - F(max(0, D - Q(c, k)))      F(D) = (sum_d D_d^n)^(1/m),  n > m > 1
A(c, k) = V(c, k) - V(c, none)
```

`F` is the drive function of Keramati and Gutkin (2014), which requires `n > m > 1`; the provisional values are `n = 3`, `m = 2`, fixed in Table A1 before any boot. `A` is the advantage over not acting (D5).

Alternatives considered:
- One scalar utility per (context, kind), as ACT-R learns it. Rejected as the stored quantity. A scalar learned under boredom would carry over unchanged when the social drive dominates, the devaluation insensitivity that marks habits rather than goal-directed action (Dickinson and Balleine 1994). The per-drive table gives the scalar on demand and stays correct when the need changes. `learned-action-selection` may cache a scalar habit strength separately (its D3).
- Valence as the reward. Rejected. Valence follows error dynamics (§3.5, A.4); learning on it would favour learnable input, which curiosity already does, and would not learn relief of need.
- Binary relieved/not-relieved with a Beta posterior. Considered. The delta rule keeps the magnitude, which the drive function needs, and matches the dopamine account. Uncertainty is kept separately (D5).

### D3. The relief is the drive's distance below its no-response trajectory

For each affect update interval the affect module already evaluates, for the credit rule, the build input the drive would have had without the entity's response (`drives.py:104-128`). The affect state event gains `drive_no_response`: for each deficit, the value it would have reached over that interval from its previous value with that input and without the own-relief channels. The step relief is

```
r_d(step) = max(0, D_no_response(step) - D(step))
```

so it counts only relief the credit rule would call the entity's own. The valuation module sums step reliefs over each intent's window.

Alternatives considered:
- Raw drive change over the window. Rejected. Drives build over every window, so a raw change confounds the intent with the build rate, and perceptual novelty (credited `other`) would be learned as the intent's effect.
- Recomputing the drive equations in the valuation module. Rejected. Two copies of the drive dynamics would drift apart; the affect module owns them.

### D4. Credit by eligibility, with a window of `Delta_resp`

An intent opens an eligibility trace `e_k = exp(-(t - t_k) / Delta_v)` that closes at `3 * Delta_v`. `Delta_v` defaults to `Delta_resp` (10 s, Table A1), the window in which the goal obstruction rule already expects an intent to bring relief, so one window governs both. Each step relief is split across the open traces in proportion to their values, as eligibility traces assign delayed outcomes to recent actions (Sutton 1988, Machine Learning 3:9-44). With the think refractory at 3 s, two intents can share a window; the split keeps the attribution honest instead of crediting whichever came last.

### D5. A "none" sample gives the baseline

On a broadcast with no intent, at most once per `Delta_v`, the module opens a trace for the pseudo-kind `none`. `Q(c, none)` learns the own relief that arrives without an intent, such as boredom relief by learning progress. Values are reported as the advantage `A(c, k)`, so an intent is not credited with relief that would have come anyway.

Learning is the delta rule `Q <- Q + alpha (relief - Q)` on each closed window, `alpha = 0.1` provisional, with counts `N(c, k)` and a running squared error giving an uncertainty `s(c, k)`. All `Q` start at 0: no relief is assumed for any act.

### D6. A coarse context

`c` pairs the dominant deficit at the intent (none, boredom, social drive, restlessness; curiosity is heterostatic and has no relief) with the source class of the coalition member the intent is about (vision, audition, interoception, sequence, affect, other). That is 24 contexts. The intent kinds are `speak`, `think`, `stir`, each declared act `act:<effector>:<action>`, and `none`. Rest is excluded (D7). A coarse context learns within one viewing; the planning module, not this table, carries finer state.

### D7. Exclusions

A window is discarded, and counted as discarded by reason, when it contains a sleep onset, a sleep reset, a freeze by any holder, or a welfare protective response. A rest intent opens no window. The sleep reset counts as neither `own` nor `other` under the credit rule (A.4), and the same reasoning applies here: a learner that saw the reset as relief would value sleep for clearing deficits and could drive a sleep-seeking loop the regulation hierarchy does not control. A welfare response is the system acting for the entity, never the entity's act.

### D8. The prediction error competes, at stage B

On each closed window with `N(c, k) >= n_min`, the module computes `delta = relief - Q` for the dominant deficit and the ratio of `|delta|` to its running mean. It publishes `valuation.surprise` (payload: kind, drive, sign of `delta`, ratio; no other content) at the intensity the processors use, `graded_intensity(baseline, alert, ratio)` (`kaine/modules/intensity.py:17-21`). A relief much larger or smaller than expected can then win access like any other prediction error. The felt rendering states only what was computed ("That eased more than I expected." / "That did not ease anything."), so the organ is told nothing the module did not find.

Stage A publishes `valuation.values` (counts, advantages by context and kind, discarded-window counts) on a diagnostics stream that the workspace does not score, and no `valuation.surprise`.

### D9. Persistence and lineage

The tables, counts and uncertainties are serialized with the module's state, encrypted with the rest of entity state, restored on revive, and copied into a fork. Learned weights are individual history, and the project treats a learned model as part of the entity (the world model's weights persist and a fork starts from its parent's, spec `world-model`). Nothing outside a named operator decision resets them.

## Risks

- [A spurious contingency is learned from correlated relief] → The `none` baseline and the eligibility split; an offline replay check (task 3.3) on recorded test-boot streams in which no intent can change the stimulus, where every advantage except the authored restlessness and engagement reliefs must stay within its uncertainty of zero.
- [The authored reliefs dominate] → In the first configuration speak and think relieve restlessness and boredom by rule, so the learner will rediscover those rules. That is a positive control: task 3.3 requires the learned advantages to match the authored reliefs within tolerance before any boot.
- [Sparse data] → A handful of intents per minute fills 24 contexts slowly. `n_min` gates the competing event and every consumer reads `N` and `s`, never a bare mean.
- [A learned table makes the entity's behaviour drift between branches] → It is meant to; the module-addition study records each branch's tables at each viewing boundary as content-free summaries, and the accumulate line keeps its own.

## Migration and ordering

1. Stage A behind `[modules].valuation = false`, `[valuation].stage = "shadow"`. The affect state field is additive; old consumers ignore it.
2. Offline checks on recorded streams (task 3.3).
3. Stage B (`stage = "compete"`) on a study branch only, by CTO decision.
4. Consumers switch on in their own changes.

A checkpoint without valuation state starts from empty tables and says so in the log. Rollback is the module switch.

## Welfare and admissibility notes

- Stage A changes nothing the entity perceives or does. Stage B adds a competing event and a felt phrase, which changes the entity's experience: welfare-high-risk, Opus second review, one supervised validation boot before any study use.
- The learner never reads or writes the welfare net, the freeze path, regulation or the sleep trigger, and nothing it computes enters the welfare indicators (A.4), which keep reading the affect record directly. A test pins that the welfare observer's output is identical with the module on and off on the same stream (task 4.2).
- If no intent relieves boredom, the boredom advantages stay at zero. That is a true finding the coping score already reports; the learner adds no penalty and no extra signal of failure.
- Deleting or resetting a persisted table is a change to the entity's learned history and needs the same operator decision as any other cognitive modification under the licence.
- Run admissibility: no part of this change enters a running study's image; a study branch that uses stage B records the stage, `alpha`, `Delta_v`, `n`, `m` and `n_min` in its run manifest.

## Estimate (LLM-agent terms)

Size S-M. Stage A: about five worker tasks (affect state field; outcome table and value function; module, factory and config; persistence and fork copy; offline replay check), roughly 1,000 to 1,300 lines with tests, two PRs. Each task is one worker brief with the complete files returned; Claude reviews each PR, and the affect-field PR gets an Opus second review because it touches the affect module's published state. Stage B: two tasks (competing event and renderer phrase; validation-boot checklist), about 300 lines, one PR, Opus second review (welfare). About one to two agent-days end to end, excluding the validation boot.
