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
- **For the most salient `nous.proposal` in the coalition:**
  - `think` gives a `think` intent and `speak` gives a `speak` intent. Each has `about` set to a short content-free summary of the coalition's top non-Nous event (the same summary the drive policy uses), `entry_id` set to that event's entry id, and `origin: "nous"`.
    - The existing one-in-flight guards for speak and think apply: they are the same guards, shared with the wrapped policy. The self-initiated report policy's refractory periods apply when it is the wrapped policy.
    - No self-response: a proposal whose only other coalition content is the entity's own speech is declined, as `"self_response"`.
  - `rest` gives a `rest` intent (`kind: "rest"`, `about: "rest"`, `origin: "nous"`).
- **Outcome.** For EVERY `nous.proposal` it sees, Volition publishes `volition.proposal_outcome` on its own stream, `volition_feedback.out` (source `volition_feedback`; NOT `volition.out`, which stays intent-only and silent on inhibited snapshots) with `proposal_id`, `realized: bool` and `reason` ∈ {`"realized"`, `"inhibited"`, `"in_flight"`, `"refractory"`, `"superseded"`, `"self_response"`, `"disabled"`}.
  - On an inhibited snapshot the step produces no intents and publishes nothing to `volition.out`. Outcomes for proposals in that coalition still go to `volition_feedback.out`, which no effector reads.
- **Switch.** `[nous].drive_actions` (default `true`) controls the source. When `false`, the source is not installed and every proposal's outcome is `"disabled"`. That keeps Nous's learning honest in an ablation run.

### Nous learns from what was actually done
- Nous reads `volition_feedback.out` for `volition.proposal_outcome` with a small consumer, the same peer-stream pattern other modules use, with its cursor seeded at the tail on boot.
- Before each engine step, it calls `record_taken_action(idx)` for its most recent proposal whose outcome has arrived: the proposed action's index if realized, otherwise the `no_op` index.
- A proposal whose outcome has not arrived by the next step is treated as not taken (`no_op`), because nothing observed it happen. A late outcome is counted (`late_outcomes`) and ignored.
- The CL1 drive-mode wrapper already calls `record_taken_action`. It keeps precedence for its own step (it runs inside `step()`), and the proposal feedback applies on top at the next step.

### Rest requests
- Lingua ignores `kind == "rest"`, and Praxis already ignores non-`act`.
- Hypnos reads `volition.out` for `intent.rest` in its existing consumer loop.
  - It honours one as a sleep trigger through the same `_sleep_lock` / `_sleep_pending` guards, with reason `"requested"`.
  - It honours it only if at least `requested_rest_min_interval_s` of entity time (default 1800) has passed since the last sleep ended, of any trigger.
  - Otherwise it drops the request with a structured log line and a content-free `hypnos.rest_request` event (`accepted: false`, `reason: "too_soon"` / `"busy"`). The acceptance is announced only once the sleep has started (see the review decisions below).
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

## Decisions after the second review

- **One guard state per kind.**
  - While the source's own speak/think guard is armed, it drops the wrapped policy's intents of that kind. While the wrapped policy reports one in flight, the source declines proposals of that kind.
  - The refractory interval for a kind counts the most recent intent of that kind from EITHER side. The interval values come from `[volition].speak_refractory_s` / `think_refractory_s` (defaults 8 / 3).
  - Guards clear, on EVERY call (including inhibited observation and the ablation path), when the entity's own speech of that kind is conscious, or after the 48 s guard timeout.
- **Referent.** It is the most salient coalition member that is neither a Nous proposal nor the entity's own speech (source `lingua`). If none exists, the proposal is declined `self_response`.
- **Which proposal.** The coalition is ordered by salience, so the proposal considered is the MOST SALIENT one (the first), and the others are `superseded`.
- **Rest.** The source declines a rest proposal as `refractory` until `[hypnos].requested_rest_min_interval_s` has passed since the source's last rest intent, so refusals by Hypnos are rare.
  - Hypnos publishes `hypnos.rest_request` at salience 0 (diagnostic, never competing for the workspace). It announces `accepted: true` only after the sleep has actually started; otherwise it announces `busy`.
  - At construction it seeds the end of the last sleep from the boot time. The last-sleep time is deliberately not persisted, so boot time is the conservative bound: a restart cannot bypass the interval.
  - There is no `frozen` reason. An operator freeze stops the cycle, so no broadcast and no new intent occurs. Hypnos (a module) may not read the cycle's control state.
- **Learning records what happened, when it happened.** Before each step, the action taken is that of the most recent proposal whose `realized` outcome arrived since the previous step, else `no_op`. Nous keeps the ids and actions of its last 32 proposals, so an outcome that arrives several steps after its proposal (Nous lagged the broadcast) is recorded as the action taken at the step it becomes known: the action did happen then. Outcomes for unknown proposal ids (for example from before a restart) are counted and ignored. A failed or timed-out step changes none of this.
- **Precise attribution.** Lingua's `internal_speech` / `external_speech` payloads carry the realized intent's `origin` when present. The ignition audit classifies a realization as `nous_initiated` from its own payload, not by guessing the last intent of that kind.
- **Audit window (a pre-existing defect).** The audit window starts at the PREVIOUS sleep's time, which is captured before the current sleep overwrites it. Before this fix every audit window started at the current sleep, so its counts read zero.
- **Ablation precedence.** With `drive_actions = false`, every proposal's outcome is `disabled`, including on inhibited snapshots.
- **Research taxonomy.** It keeps `origin` on `intent.speak` / `intent.think` / `intent.act` / `intent.rest`. Lingua speech events are content and stay out of the taxonomy.
- **Red-team harness.** Its scenarios cover the proposal path: a forged `act` proposal is never realized, and an inhibited proposal is never realized.

## Decisions after verification

- **One guard state, owned by the wrapped policy.**
  - Every action-selection policy (the default, drive-biased and self-initiated report policies) gains `note_external_intent(kind, when)`. It arms that policy's own in-flight guard for the kind, stamps the arm time, and for the report policy updates the last-report time of the kind.
  - When the source realizes a Nous think or speak, it calls this. The wrapped policy then declines that kind by its own rules and clears it by its own rules; nothing is dropped after the wrapped policy has decided.
  - Only for a kind the wrapped policy does not guard (any kind for a plain callable; `think` under the default policy, which guards only `speak`) does the source keep its own guard and filter. The in-flight check reads both the source's guard and the wrapped policy's `<kind>_in_flight`.
  - The refractory check for a proposal still counts intents of the kind from either side.
- **Rest outcomes come from Hypnos.**
  - `intent.rest` carries the `proposal_id`. Volition reports a rest proposal's outcome as `realized: false`, `reason: "forwarded"`. That is not final, and Nous keeps the id.
  - Hypnos's `hypnos.rest_request` carries the same `proposal_id`. Nous reads it from `hypnos.out` and treats `accepted: true` as the realization (the action taken at the tick it becomes known) and `accepted: false` as declined.
  - The source's rest refractory is measured on the entity clock and seeded at construction, which keeps forwarding rare. Hypnos remains the authority.
- **Acceptance at sleep start.** Hypnos publishes `hypnos.rest_request` `accepted: true` immediately after `hypnos.sleep.started` for a requested sleep, from inside the pipeline. It publishes `busy` if the lock was taken, and `aborted` if the pipeline started but failed.
- **A failed or timed-out step keeps a realized action pending.** It is recorded at the next step that commits. Nous clears it only after a successful step.
- **The wrapped policy never sees a proposal.** The source hands it the snapshot with every `nous.proposal` removed from the coalition and from the salience scores. Otherwise the self-initiated report policy reports on the proposal itself: a salient proposal wins the report signal, the report policy thinks about "nous", and the proposal is superseded by a thought about itself. Removing it also keeps the wrapped policy's decisions identical with `drive_actions` on or off, so the ablation compares like with like.
- **Vox origin.** `vox.synthesized` carries the `origin` of the `external_speech` it voices, so the audit attributes it from evidence.
- **Every guard times out.** A realization that never becomes conscious (organ error, Lingua failure, the speech losing the coalition) must not mute a kind forever. The self-initiated report policy therefore gets the same 48 s guard timeout the default and drive policies have, for both its speak and its think guard. This holds whether the report policy armed the guard itself or a Nous intent armed it through `note_external_intent`. Like the other policies' guards, it is timed on wall time, because it covers real generation and playback, while the report refractories stay on the subjective clock.
- **Guards clear by channel.** The default policy clears its speak guard only on the entity's `external_speech`, as the drive and report policies do. A Nous think's `internal_speech` no longer releases a speak that is still in flight.
- **A Nous speak can be interrupted.** A Nous speak arms the report policy's speak guard, so when `interrupt_threshold` is set, a more salient coalition can interrupt a Nous utterance exactly as it interrupts the policy's own.
- **Forwarded rests are counted separately.** The ignition audit counts `reason: "forwarded"` outcomes as `nous_proposals_forwarded`, not as declined, because Hypnos decides them. An accepted one appears as a requested sleep. Nous ignores a `forwarded` outcome whose id Hypnos has already resolved, instead of counting it as unknown.
- **The research log keeps the Nous counts.** The research-event observer's allowlist for `hypnos.ignition_audit` includes `nous_initiated` and the three proposal counts. A test pins that every numeric count the audit publishes is allowed.
