## Why

The action-selection module decides what the entity says and thinks with two fixed bars on the coalition's best score: a speak bar of 0.6 and a think bar of 0.45 (`kaine/workspace/report_policy.py:82-83`; paper A.6, Table A1), plus refractory intervals, in-flight guards and a signature check. The paper calls the bars "a heuristic stand-in for the expected-free-energy decision of Whyte and Smith (2021)" (§3.3) and lists among its limitations that "selection, action, affect, and language do not learn" and that there is "no declarative or procedural memory" (§9). In the Common Model of Cognition, procedural memory selects an action on each cycle and learns its utility (Laird, Lebiere and Rosenbloom 2017, AI Magazine 38(4):13-26); KAINE has no counterpart. The bars are authored, they never change with the entity's history, and §9 notes that "at resting arousal without interest no report bar is reachable".

Design only. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main cb41895b)

- The report rule: one intent per accessed broadcast, speak before think, guards released on the organ's output, refractory intervals on entity time, a signature check on speech (`kaine/workspace/report_policy.py`; spec `self-initiated-report`).
- The policy seam: `[action_selection].policy` selects the policy, and wrappers compose (`kaine/cycle/__main__.py:2282-2373`): the planning proposal source wraps the report policy (spec `action-selection`, "Action selection realizes conscious Planning proposals under the existing gates").
- A precedent for a learned, bounded bias on selection: the interest goal factor, which lifts a source's priority by its learning progress through a provider the cycle refreshes (`interest-goal-factor`, archived 2026-10-19).
- The learner this change reads: `drive-reduction-learning` gives each (context, intent kind) an advantage over not acting, with a count and an uncertainty.

### What is missing

- Nothing in action selection learns. A kind that never relieves anything and a kind that always does are selected by the same bars.
- No procedural memory: no record of which selections the entity has made in which situations, and no habit.

## What Changes

A design, settled first in the paper and then in code.

1. A learned report policy, `learned_report`, keeps every guard, refractory interval and the signature check of the current rule and replaces each fixed bar by an effective bar per context: the authored bar moved by the kind's learned advantage, in proportion to how much evidence there is, within a fixed bound and never down to the access threshold. The authored bars become the starting point, and experience moves them, as corticostriatal learning moves a decision threshold (Lo and Wang 2006).
2. When more than one kind clears its bar, the policy chooses among them by a softmax over their advantages with a fixed temperature, seeded from the run seed. With no evidence the choice reduces to today's order (speak, then think, then act), and still at most one intent per broadcast.
3. A habit table (stage 2, its own switch, off by default): a value-free strength per (context, kind) that grows with repetition of a selection (Miller, Shenhav and Ludvig 2019), combined with the advantage by relative certainty (Daw, Niv and Dayan 2005). It is the procedural memory in the CMC sense. It persists with the valuation module's tables.
4. Paths that stay outside learning: rest intents (regulation tier 3, the planning module's rest, the developmental rest), the welfare net, the operator-response path of the default policy, and the interrupt bar.
5. A record: the run manifest names the policy and its parameters, and the content-free research log records each kind's effective bars at every viewing boundary.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `action-selection`: a learned report policy whose bars and choice among eligible kinds follow the learned advantages within bounds, with the guards unchanged and rest and welfare paths outside learning.
- `valuation`: a habit table, persisted with the outcome tables, updated from the selections the action layer makes.

## Impact

- `kaine/workspace/report_policy.py` (or a sibling `learned_report_policy.py` sharing the guard code), `kaine/cycle/__main__.py` policy selection, a values provider fed from `valuation.values`, `kaine/modules/valuation/` (habit table), `config/kaine.toml` (`[action_selection.learned]`), docs for action selection and valuation.
- Every `config/studies/workspace_mediation_*.toml` arm keeps `policy = "self_initiated_report"`.
- Paper: §3.3 and A.6 gain the learned bar and choice rule as a held option; §9's line on selection not learning stays true of the first configuration; Table A1 gains `b_max`, `N_0`, `A_scale`, the temperature and the habit rate.

## Dependencies and start condition

- Gate: the workspace-mediation ablation (§6.3) has run, because the report bars decide which accessed broadcasts produce text and the ablation's arms must share one report rule.
- Dependency: `drive-reduction-learning` stage A merged and its offline replay check (its task 3.3) passed.
- Study placement: a branch of its own in the module-addition study after the valuation module's branch, or a later study; a CTO decision recorded in the study design.
