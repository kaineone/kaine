## Decisions

### Model
- **Control and actions.**
  - There is one control factor, the action factor, with four actions and horizon 1 by default.
  - `B_action_dependencies = [[0], [0], [0], [0]]`: every state factor's transition depends on the action.
  - The action factor keeps "the next action state is the action taken", so the being observes its own last action.
- **Perceptual factors** `f` in {salience, affect, event cluster}: `B_f` has shape `(n_f, n_f, 4)`. Its initial expected value is the same for every action: `persistence·I + (1 − persistence)·uniform`, with `persistence = 0.8`.
- **Prior over transitions.** `pB_f = concentration · B_f`, with `concentration = 1.0` per column. The prior is weak, so a few dozen experiences of an action dominate it.
- **Settings.** `persistence` and `concentration` are `[nous]` settings with these defaults. They express how much the being assumes the world persists and how sure it starts out, not what any action does.
- **A, C and D are unchanged.** The preference over the highest salience band predates this change and stays as it is. This change adds no preference.

### Engine
- **Agent construction:** `pymdp.agent.Agent(A, B, C, D, pB=pB, A_dependencies=…, B_action_dependencies=…, policy_len=…, use_param_info_gain=True, learn_B=True, …)`.
- **Per step:**
  1. Encode the observation.
  2. Infer states with `empirical_prior` equal to the carried prior (initially `D`).
  3. Infer policies, then select the action (argmin EFE, ties to the lower index).
  4. Update `pB` from the previous posterior, the action taken on the previous step, and the current posterior (`infer_parameters`, or the pymdp learning call its API provides).
  5. Compute the next carried prior with `update_empirical_prior(action, posterior)`.
- **The timeout and error paths are unchanged.** The step's action falls back to `actions[0]`, no learning update is applied for a timed-out or failed step, and the carried prior is kept.
- **Serialization.** `serialize()` adds `{"pB": per-factor nested lists, "carried_prior": per-factor lists, "last_action_index": int}`. `deserialize()` validates the shapes, finiteness and non-negativity, and rebuilds the agent with that `pB`. A snapshot without `pB` (older beings) starts from the prior and logs it.

### Limits and honesty
- **Budget.** The complexity envelope and the ≤200 ms median decision budget still apply. The learning update runs after the action is published, so it is not on the decision's critical path. It runs within the same timeout guard.
- **Records.** `nous.policy` carries `param_info_gain_used: true`. `nous.belief` is unchanged.

## Verification
- **Golden run.** Over the 192 encodable observations, with a fresh learned model driven through a sequence of steps, Nous chooses more than one action. Before this change it chose only `no_op`.
- **Learning.** In a synthetic loop where one action reliably raises salience, `pB` for that action concentrates on the raising transition. With the existing high-salience preference, Nous comes to choose that action more often than chance after N steps.
- **Carried belief.** A step's prior equals the previous posterior propagated through B under the action taken.
- **Preservation.** A serialize → deserialize round trip reproduces `pB`, the carried prior and the next decision. An older snapshot starts from the prior.
- **Existing requirements.** The active-inference benchmark bars and the ≤200 ms median still hold.
