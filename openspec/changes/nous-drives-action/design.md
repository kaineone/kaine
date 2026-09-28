## Context

- **Nous** runs on every workspace broadcast with selected events, including inhibited ones. It publishes `nous.belief` and `nous.policy`, and for think/speak an unsigned `intent.act` on `nous.out`. The engine commits the selected action as the taken action (`_prev_action`) unless `record_taken_action` overrides it before the next step. Only the CL1 drive mode calls that today.
- **Volition** (`kaine/workspace/volition.py`) runs after each successful experiential broadcast.
  - It returns nothing on an inhibited snapshot, and signs only `act` intents (per-boot HMAC).
  - It publishes intents on `volition.out`, the only intent stream.
  - Its policy is injectable: the default, drive-biased (`drive_policy.py`) or self-initiated report (`report_policy.py`).
  - Each has one-in-flight guards, and the report policy adds refractory periods and novelty checks.
- **Lingua** reads `volition.out` and realizes `speak`/`think` by payload `kind`, with one generation stream.
- **Praxis** reads only `kind == "act"`.
- **Hypnos** sleeps on `soma.fatigue` crossed, on `soma.regulation` `request_maintenance`, or on its interval poll. All three share one lock and pending flag.
- **The ignition audit** links realizations to intents and counts `nous.out` `intent.act` as unrealizable.

## Decisions

### A Nous choice must become conscious before it is acted on
- **Nous publishes `nous.proposal`** in place of `intent.act`, and only for think, speak or rest.
  - Payload: `proposal_id` (uuid4 hex), `action` (the action name), `kind` (`think` | `speak` | `rest`), `step` (the Nous step counter), `preference` (see below).
  - It is content-free.
  - `no_op` publishes nothing.
- **Salience** is `baseline_salience + preference × (alert_salience − baseline_salience)`.
  - `preference` ∈ [0, 1] is the softmax probability of the chosen action over the per-action negative EFE, at unit precision.
  - A strongly preferred action is more likely to win the workspace; an indifferent one rarely does.
  - Nothing is hardwired: the strength comes from Nous's own inference.
- **Volition.** A proposal is acted on only when it is in the conscious coalition of a non-inhibited experiential broadcast, where Volition sees it.
  - This is global-workspace control ("control emerges from workspace competition", paper v4). It also means the inhibition gate applies without any new code path.

### The Volition proposal source
- **`NousProposalSource`** in `kaine/workspace/nous_proposals.py` is a policy wrapper. It composes with whatever policy is configured and runs after it on the same snapshot.
  - It yields at most one intent per snapshot.
  - It never overrides a user-response or drive intent already chosen for that snapshot. If the wrapped policy produced a `speak`, a `speak` proposal is declined as `"superseded"`.
- **For the newest `nous.proposal` in the coalition:**
  - `think` gives a `think` intent and `speak` gives a `speak` intent. Each has `about` set to a short content-free summary of the coalition's top non-Nous event (the same summary the drive policy uses), `entry_id` set to that event's entry id, and `origin: "nous"`.
    - The existing one-in-flight guards for speak and think apply: they are the same guards, shared with the wrapped policy. The self-initiated report policy's refractory periods apply when it is the wrapped policy.
    - No self-response: a proposal whose only other coalition content is the entity's own speech is declined, as `"self_response"`.
  - `rest` gives a `rest` intent (`kind: "rest"`, `about: "rest"`, `origin: "nous"`).
- **Outcome.** For EVERY `nous.proposal` it sees, Volition publishes `volition.proposal_outcome` on the `volition.feedback` stream (NOT `volition.out`, which stays intent-only and silent on inhibited snapshots) with `proposal_id`, `realized: bool` and `reason` ∈ {`"realized"`, `"inhibited"`, `"in_flight"`, `"refractory"`, `"superseded"`, `"self_response"`, `"disabled"`}.
  - On an inhibited snapshot the step produces no intents and publishes nothing to `volition.out`. Outcomes for proposals in that coalition still go to `volition.feedback`, which no effector reads.
- **Switch.** `[nous].drive_actions` (default `true`) controls the source. When `false`, the source is not installed and every proposal's outcome is `"disabled"`. That keeps Nous's learning honest in an ablation run.

### Nous learns from what was actually done
- Nous reads `volition.feedback` for `volition.proposal_outcome` with a small consumer, the same peer-stream pattern other modules use, with its cursor seeded at the tail on boot.
- Before each engine step, it calls `record_taken_action(idx)` for its most recent proposal whose outcome has arrived: the proposed action's index if realized, otherwise the `no_op` index.
- A proposal whose outcome has not arrived by the next step is treated as not taken (`no_op`), because nothing observed it happen. A late outcome is counted (`late_outcomes`) and ignored.
- The CL1 drive-mode wrapper already calls `record_taken_action`. It keeps precedence for its own step (it runs inside `step()`), and the proposal feedback applies on top at the next step.

### Rest requests
- Lingua ignores `kind == "rest"`, and Praxis already ignores non-`act`.
- Hypnos reads `volition.out` for `intent.rest` in its existing consumer loop.
  - It honours one as a sleep trigger through the same `_sleep_lock` / `_sleep_pending` guards, with reason `"requested"`.
  - It honours it only if at least `requested_rest_min_interval_s` of entity time (default 1800) has passed since the last sleep ended, of any trigger.
  - Otherwise it drops the request with a structured log line and a content-free `hypnos.rest_request` event (`accepted: false`, `reason: "too_soon"` / `"busy"` / `"frozen"`). An accepted request emits `accepted: true` before `hypnos.sleep.started`.
- Non-interruptibility, bounded deferral, operator-freeze preemption and the welfare monitors are untouched. A requested rest is an ordinary sleep.

### Audit, taxonomy, rendering
- **Ignition audit:**
  - A realization whose intent carries `origin: "nous"` is classified `nous_initiated`, a fourth category, before the input/drive/self rules.
  - `hypnos.sleep.started` whose trigger is `"requested"` counts as a realized `rest`.
  - `volition.proposal_outcome` gives `nous_proposals_realized` / `nous_proposals_declined` counts.
  - `unrealizable_nous_intents` stays as a guard counter for any `intent.*` event on `nous.out`. Nous publishes none, so it should read zero; a non-zero value means some other component published an intent on the wrong stream.
- **Taxonomy:** the research event taxonomy adds `nous.proposal`, `intent.rest`, `volition.proposal_outcome` and `hypnos.rest_request`.
- **FaithfulRenderer:** templates for `nous.proposal` ("Nous proposes to think/speak/rest"), content-free.
- **Run identity:** it records `nous.drive_actions`.

## Risks

- **Nous may rarely win the workspace**, and so rarely act. That is the intended emergent behaviour, not a failure; the audit's `nous_proposals_declined` makes it visible.
- **An exploring Nous may request rest often.** The minimum interval bounds it, and every refusal is logged.
- **The learning semantics change**, so pre-change `pB` is not comparable. `drive_actions` in run identity keeps runs separable.
