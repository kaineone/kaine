# Design: multi-step planning

## Context

Discrete active inference scores a policy, a sequence of actions, by its expected free energy, which has a pragmatic part (how far predicted outcomes match prior preferences) and an epistemic part (expected information gain) (Da Costa et al. 2020, J Math Psychol 99:102447; Parr and Friston 2017, J R Soc Interface 14:20170376). Sophisticated inference evaluates beliefs about future beliefs recursively over a tree of actions and outcomes, and prunes improbable outcomes and poor actions so deep horizons stay tractable (Friston, Da Costa, Hafner, Hesp and Parr 2021, Neural Comput 33:713-763). People planning several steps ahead prune the decision tree where a large loss appears (Huys et al. 2012, PLoS Comput Biol 8:e1002410), and spend more model-based effort when it pays (Kool, Cushman and Gershman 2016, PLoS Comput Biol 12:e1005090).

Preferences in active inference are prior beliefs over outcomes. Pezzulo, Rigoli and Friston (2015, Prog Neurobiol 134:17-35) cast homeostatic regulation this way: interoceptive set points are prior preferences, and goal-directed control serves them. Allostasis treats regulation as prediction of need (Sterling 2012, Physiol Behav 106:5-15). Keramati and Gutkin (2014) give the drive function whose fall is reward, which `drive-reduction-learning` adopts.

Planning with a learned model can be trained on simulated experience as well as real (Dyna; Sutton 1990, Machine Learning Proceedings 1990:216-224). Hippocampal replay is well described as prioritized access to memories for planning (Mattar and Daw 2018, Nat Neurosci 21:1609-1617).

KAINE's planning model sits on workspace-level states: the leading member's salience band, the affect quadrant and an event cluster (`generative_model.py:14-25`). Its world model also models the sequence of broadcast summaries, not a scene (paper §4 table; `kaine/modules/world_model/encoder.py:1-20`). This change plans over those states plus the deficits. It does not claim planning over a perceived world.

## Decisions

### D1. Add a deficit factor rather than a reward

The planning model gains factor 4, `deficit`, with states `none`, `boredom_high`, `social_high`, `restlessness_high`: the dominant deficit when it is at or above its threshold, else `none` (curiosity is heterostatic and has no deficit state). Its modality is observed from the latest `affect.state` (`drive_above` and the drive values). Its transitions depend on the action, start from the same broad prior as the other perceptual factors, and are learned (spec `planning-active-inference`, "Planning's actions have consequences it learns").

With five factors of at most four states, four actions and horizon 3, the envelope product is 240, under 4096.

Alternatives considered:
- A scalar reward modality fed by the valuation module's advantages. Rejected. It would feed the same evidence into two learners that both bias selection, and it turns active inference into reward maximization with a second critic.
- The full drive vector as three factors. Rejected for now: 64 joint deficit states for a handful of transitions per minute would learn too slowly. The dominant deficit carries the planning-relevant part.

### D2. Preferences derived from the set point, none authored

- Salience, affect quadrant and event cluster: flat preferences (all zero). The authored "highest salience" disposition is removed. Engagement with salient content, where it pays, has to come from epistemic value or from learned deficit consequences.
- Deficit: `C(none) = 0`, and `C(d_high) = -kappa * F(theta_d e_d)`, where `F` is the drive function of `drive-reduction-learning`, `theta_d` the drive's threshold and `e_d` its unit vector, so each deficit state's preference is the negative of the drive function at that deficit's threshold. `kappa` is a precision, provisional 4, fixed in Table A1. The set point (zero deficit) is the one innate element, cited at the code site to Pezzulo et al. (2015) and Sterling (2012).

Alternatives considered:
- Learned preferences, a Dirichlet prior over `C` updated by observed outcomes (Sajid, Ball, Parr and Friston 2021, Neural Comput 33:674-712; Sajid et al. 2021, arXiv 2106.04316). Rejected as the default. In a constant environment such agents learn precise preferences for the outcomes they meet, so an entity kept in deprivation would come to prefer deprivation. That is an adaptive-preference failure with welfare weight. It stays available as an ablation arm, off by default.
- A preference for pleasant affect quadrants. Rejected: valence follows error dynamics (A.4), and an authored valence preference is the same kind of hand-written disposition as the salience one.
- Keep the salience preference and add the deficit one. Rejected: the salience preference has no cited basis.

### D3. Horizon three by enumeration first, sophisticated inference when actions grow

Both engines already enumerate `actions^H` policies and report correct per-action EFE. At four actions and `H = 3` that is 64 policies, within what the NumPy engine runs at the benchmark's horizon 4 (256 policies, `numpy-nous-engine` design). The planning module proposes the first action of the best policy and replans on the next broadcast, so no plan is committed.

When `planning-act-proposals` adds the declared actions of attached effectors, enumeration grows as `actions^H`. The engine then switches to sophisticated inference with two pruning thresholds: outcomes with predictive probability below `p_min` and actions whose EFE exceeds the best sibling by more than `Delta_G` are not expanded (Friston et al. 2021). The pre-build latency benchmark (200 ms median) and the 250 ms timeout apply unchanged.

Alternatives considered:
- Monte Carlo tree search over the world model. Rejected: it needs a reward function and a rollout policy, adds stochastic latency, and drops the epistemic term that makes active inference the paper's choice.
- A successor representation (Stachenfeld, Botvinick and Gershman 2017, Nat Neurosci 20:1643-1653; Momennejad et al. 2017, Nat Hum Behav 1:680-692). Considered. It gives cheap multi-step predictions with good neural support, but caches policy-dependent predictions that adapt slowly when transitions change, and it has no information-gain term. Kept as a possible ablation.
- The language organ's inner speech as the deliberation channel (CoALA-style). Rejected: the paper states the organ is not used to reason (§3.5), and reversing that is a separate decision.

### D4. The world model trains the transitions offline, at reduced weight

After `world-model-action-outcomes`, the world model's transition takes an action. During sleep's scenario window the world model starts from up to `n_seed` recent waking latent states, rolls each candidate planning action forward `H` steps, and decodes each imagined step into the planning model's factor states with the same encoding the waking path uses (salience band, affect quadrant, event cluster, deficit). Each imagined transition adds `w_im` (provisional 0.25) to the planning model's Dirichlet counts, under the existing concentration cap. Lived transitions keep weight 1.

Alternatives considered:
- Query the world model online, per branch, each broadcast. Rejected. The JAX or NumPy RSSM step per branch would not fit the 200 ms bound, and waking cycles must not wait on it.
- Replace the planning model's transitions with the world model. Rejected. The world model has no discrete state and no epistemic term over its own parameters, and the planning model's learned transitions are already the entity's preserved sense of agency (spec `planning-active-inference`, "Belief carries over and the learned model is preserved").

### D5. A sleep reset is not a consequence the deficit factor learns

When the step between two planning updates contains a sleep onset or reset, the planning module updates the transitions of every factor except `deficit`. Otherwise it would learn that `request_maintenance` takes every deficit to `none` and would plan sleep as an escape from deprivation, a route the paper rules out for the fetal state cycle ("a boredom stall abandons its goal and starts no rest", §3.5) and that the regulation hierarchy, not the planner, governs. Imagined steps never cross a sleep.

Whether a mature entity may learn rest as a relief from boredom is a welfare question for the paper change (open item 1).

### D6. Benchmark

The active-inference benchmark (§6.4) gains a two-step task: a deficit observed high falls only if an action is followed by a second, different action, with the tabular Q-learning baseline matched on observations and reward (the deficit fall as its reward). A horizon ablation runs `H = 1` against `H = 3` on that task. Fail state fixed before the run: `H = 3` no better than `H = 1` by the benchmark's Mann-Whitney test at its preset minimum effect.

## Open items for the paper change

1. Whether rest may become a learned relief of deficits after maturation (D5).
2. Whether the planning module's proposals keep their current share of the action layer once `learned-action-selection` also biases the report rule, or the two are combined into one decision.
3. The §4 row: the brain-function column and what "planning" claims when its states are workspace summaries.

## Risks

- [Flat salience preference makes the planner passive] → Epistemic value stays; the preserved entity's learned transitions keep their counts. The benchmark and a recorded-stream replay compare proposal rates before and after (task 3.4).
- [The deficit factor learns slowly] → Imagined transitions add evidence in sleep; the concentration cap keeps learning responsive.
- [Imagined experience teaches false consequences] → Weight `w_im` below one, and the world model's own prediction error reported on its stream; a check that a contradicting lived transition outweighs imagined ones within a fixed number of steps (task 4.2).
- [Latency] → Envelope validator, latency benchmark, timeout guard, all existing.

## Migration and ordering

1. Deficit factor, derived preferences, sleep-span rule and horizon 3 together, behind `[planning].model_version = 2`; version 1 stays selectable for the study's branch 3 records.
2. Benchmark task and horizon ablation.
3. World-model imagination after `world-model-action-outcomes`.
4. Sophisticated inference after `planning-act-proposals`.

A preserved version-1 learned state migrates once: existing factors keep their counts, the deficit factor starts from the prior, and the log says so.

## Welfare and admissibility notes

- The planner's proposals change what the entity says, thinks and rests, and after `planning-act-proposals` what it does: welfare-high-risk. Opus second review, one supervised validation boot before study use.
- Derived preferences are chosen over learned ones for a welfare reason (D2), and the deficit factor never learns from the reset (D5).
- The planning module's proposals still pass the action layer's gates and are realized only if accessed in a non-inhibited broadcast (spec `action-selection`). Nothing here reaches the welfare net.
- Run admissibility: not built into any running study. The module-addition study's planning branch keeps model version 1; version 2 is a later branch or study, recorded in the manifest with `H`, `kappa`, `w_im`, `p_min` and `Delta_G`.

## Estimate (LLM-agent terms)

Size L. About six worker tasks over four PRs: factor, modality and encoding; derived preferences with the code-site citation; horizon 3 with envelope and latency benchmark; state migration; benchmark task and ablation; world-model imagination (after its dependency); sophisticated inference with pruning (after its dependency). Roughly 2,500 to 3,500 lines with tests. The engine work touches both engines and their golden fixtures, so it suits one worker brief per engine plus a parity task. Opus second review on every PR (welfare, and subtle numerics). About four to six agent-days spread over the dependencies.
