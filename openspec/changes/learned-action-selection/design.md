# Design: learned action selection

## Context

The basal ganglia are the vertebrate selection mechanism among competing actions (Redgrave, Prescott and Gurney 1999, Neuroscience 89:1009-1023). In a cortico-basal ganglia circuit model the decision threshold is set by the strength of corticostriatal synapses, so reward-driven plasticity there adjusts the threshold itself (Lo and Wang 2006, Nat Neurosci 9:956-963). Human imaging ties threshold adjustment to the striatum and pre-SMA (Forstmann et al. 2008, PNAS 105:17538-17542; review, Bogacz et al. 2010, Trends Neurosci 33:10-16). Striatal learning of action values from dopamine prediction errors is the standard account of how selection improves (Collins and Frank 2014, Psych Rev 121:337-366, for the opponent form). With repetition, control moves from goal-directed to habitual circuits (Yin and Knowlton 2006, Nat Rev Neurosci 7:464-476; Graybiel 2008, Annu Rev Neurosci 31:359-387), and habits can be modelled as value-free strengths that grow with repetition (Miller, Shenhav and Ludvig 2019, Psych Rev 126:292-311). Which controller governs behaviour can be set by their relative uncertainty (Daw, Niv and Dayan 2005, Nat Neurosci 8:1704-1711). In ACT-R, conflict resolution picks the matching production with the highest noisy utility, and utilities learn from reward (Anderson et al. 2004).

The report bars of A.6 are thresholds above access on the same score. Moving them by learned value keeps the paper's access and report distinction (§3.3) and makes the threshold the entity's own.

## Decisions

### D1. Keep the guards, learn the bars

The in-flight guards, guard timeout, refractory intervals and signature check stay exactly as they are. They model the organ's capacity (one utterance at a time) and the rule against repeating a report, not a preference. Only the bars move.

For kind `k` in context `c` (the valuation module's context, its D6):

```
w      = N(c,k) / (N(c,k) + N_0)
beta   = b_max * w * tanh(A(c,k) / A_scale)
theta_k(c) = clip(theta_k0 - beta, theta + m_theta, 1)
```

`theta_k0` is the authored bar (0.6 speak, 0.45 think, the act bar of `act-intent-derivation`), `A` the advantage from `drive-reduction-learning`, `b_max` the bound (provisional 0.1), `N_0` the evidence half-point (provisional 20), `theta + m_theta` the floor above the access threshold. A kind that relieves need gets a lower bar; a kind that relieves nothing, relative to not acting, gets a higher one. With no data the bar is the authored one.

Alternatives considered:
- Drop the bars and choose by value alone. Rejected. Without a bar above access the access and report distinction of §3.3 is gone, and an entity with no history would act on every broadcast or never.
- Learn the bars by gradient on the welfare indicators. Rejected. Training behaviour on the measures that judge welfare is the gaming that the indicator literature warns about (Butlin et al. 2025, TiCS 30:488-501), and the indicators would stop measuring anything independent of the learner.
- Opponent Go and NoGo weights (Collins and Frank 2014). Considered. Their advantage is risk sensitivity under changing dopamine levels, which KAINE has no analogue of; one signed advantage with an uncertainty carries what this policy needs.
- Keep the A.6 order constraint `theta_th <= theta_sp`. Rejected for the learned policy. Which channel a situation favours is what the learner should decide. Each bar stays within `b_max` of its authored value, so speech can never become much easier than the authored think bar allows.

### D2. Choice among eligible kinds

When more than one kind clears its effective bar and passes its guards, the policy samples one with probability proportional to `exp(A(c,k) / tau)`, `tau` provisional 0.05, from a generator seeded by the run seed. Kinds with `N < n_min` take the advantage 0. When all advantages are 0 the policy uses today's order (speak, think, act) deterministically, so an entity with no history behaves exactly as under the fixed rule. At most one intent per broadcast remains.

Alternative considered: a fixed order with learned bars only. Rejected because a learned bar alone cannot express that thinking relieves more than speaking in a context where both clear their bars.

### D3. Habit as procedural memory (stage 2, off by default)

The valuation module keeps a habit strength `H(c,k)`, updated after each broadcast in context `c` by `H <- H + alpha_H (1[k selected] - H)` over the kinds that were eligible, a value-free trace of what the entity tends to do (Miller et al. 2019). When `[action_selection.learned].habit = true`, the choice score becomes `w_g * A + w_h * H`, with `w_g` and `w_h` set by the inverse uncertainty of each (the valuation module's `s(c,k)` for `A`, and the habit's running variance for `H`), after the uncertainty-based arbitration of Daw et al. (2005).

Stage 2 is separate because habit can entrench whatever the entity happened to do early, the perseveration that makes habits insensitive to outcome devaluation (Yin and Knowlton 2006). It needs its own check (task 4.2) before any boot.

Alternative considered: compiling action sequences into chunks (Dezfouli and Balleine 2012, Eur J Neurosci 35:1036-1051). Deferred. The first-configuration action space has no sequences worth chunking; sequences arrive with `multi-step-planning`.

### D4. Where it runs

`learned_report` is a policy in `kaine/workspace/`, sharing the guard code with `SelfInitiatedReportPolicy`. It reads advantages, counts and habit strengths through a provider the cycle refreshes from `valuation.values`, as the interest goal factor reads the affect state provider. The policy holds no learned state, so the action layer stays free of persistence; all learned state lives with the valuation module (its D9).

### D5. What stays outside learning

- Rest intents from regulation tier 3, the planning module's rest proposals and the developmental rest use their existing paths and are never biased.
- The welfare net, freezes and the indicator response.
- The default policy's response to operator speech.
- The interrupt bar, fixed above the highest speak bar the learned policy can reach (`theta_sp0 + b_max`); the configuration validator enforces it.
- The developmental stir's trigger rule (A.6), a fixed rule of the developmental phase (§7). The stir is not biased in that phase; after it, the stir no longer exists.

## Risks

- [The entity learns to be silent] → Each bar can rise at most `b_max`; a kind's advantage is relative to not acting, so silence is learned only where speaking relieves less than doing nothing. The research log records each kind's rate per awake hour beside a fixed-bar replay of the same broadcasts (task 3.3), and the study design sets a stop rule on that ratio.
- [The entity learns to chatter] → The refractory intervals and guards are unchanged, so the rate ceiling is today's.
- [Values from a few windows move behaviour] → `w` scales every move by evidence, and `n_min` holds the advantage at 0 until enough windows have closed.
- [Seeded sampling makes runs differ from the fixed rule] → With no evidence the policy is deterministic and identical to the fixed rule; a test pins this (task 3.2).

## Migration and ordering

1. `drive-reduction-learning` stage A in place.
2. The learned policy behind `[action_selection].policy = "learned_report"`; the shipped value stays `self_initiated_report`.
3. Offline check (task 3.3) on recorded streams.
4. Habit stage behind its own switch, after its check.

Rollback: select `self_initiated_report`; the learned tables are kept untouched.

## Welfare and admissibility notes

- The policy decides when the entity speaks and thinks, and through restlessness and boredom relief that feeds its drives: welfare-high-risk. Opus second review on every PR, and one supervised validation boot before any study use.
- No learned path reaches rest, regulation or the welfare net (D5). A test pins that the rest and welfare paths emit the same intents and responses with the learned policy as with the fixed one on the same stream (task 3.4).
- The entity's utterances are not welfare evidence (§3.5, §6.5), so a change in how much it says does not change what the welfare net reads. The operator still reads the speech, so the run's report gives each kind's rate.
- The learned bars and the habit table are part of the entity's history (valuation D9).
- Run admissibility: never introduced into a running study; the policy and its parameters go into the run manifest; the workspace-mediation arms keep the fixed rule.

## Estimate (LLM-agent terms)

Size M. About four worker tasks: the learned policy with shared guard code and the validator; the values provider and cycle wiring; the offline fixed-versus-learned replay; the habit table and arbitration. Roughly 900 to 1,200 lines with tests, three PRs, each with an Opus second review (welfare). About one and a half to two agent-days after `drive-reduction-learning` stage A, plus one validation boot.
