## Context

KAINE is a global-workspace architecture (Baars GWT; LIDA lineage). Each
experiential tick, Syneidesis selects the most salient coalition, sets
`inhibited = top_score < publication_threshold`, and the cycle broadcasts a
`WorkspaceSnapshot` to all modules (`on_workspace`). In LIDA terms the broadcast
is *consciousness*; a separate *action-selection* stage decides what to DO with
conscious content. KAINE has the consciousness half (Syneidesis + broadcast) but
**not** the action-selection half — so effectors self-decide, and the
`inhibited` flag is dead. This change adds the action-selection stage.

## Goals / Non-Goals

**Goals:**
- A single place where the entity decides to act, gated by executive inhibition.
- Effectors (Lingua, Praxis) act ONLY on explicit intents — never self-trigger.
- Inhibition enforced for all effectors structurally (not per-module opt-in).
- Observable on the bus and unit-testable without booting the entity.

**Non-Goals:**
- Not a full motivational policy — drives biasing the decision is
  `drives-to-behavior`; recalled context is `spontaneous-recall`. Here the
  policy is minimal but real.
- Not promoting this to one of the paper's twelve cognitive modules — it is an
  *executive function* of the cycle/workspace layer (the paper locates executive
  inhibition "in Syneidesis"), kept thin.
- Not removing Lingua's `speak()`/`think()` methods — those remain the organ's
  realization API; only the *trigger* changes.

## Decisions

- **A distinct action-selection step, not bloating Syneidesis.** Syneidesis keeps
  its single responsibility (coalition selection + inhibition flag). A new thin
  executive component — `Volition` (`kaine/workspace/volition.py`) — is invoked
  by the cycle right after the experiential broadcast, taking the
  `WorkspaceSnapshot` (+ later, motivational state) and producing intents. This
  mirrors LIDA's separation of global workspace from action selection and keeps
  each unit testable. Alternative (fold into Syneidesis) rejected: conflates
  "what is conscious" with "what to do," and Syneidesis is already the inhibition
  authority — Volition consumes its verdict rather than re-implementing it.
- **The inhibition gate is the first thing Volition checks.** `if
  snapshot.inhibited: return []`. No intent can exist while inhibited, so no
  effector acts — enforcing §37/§147 once, for every effector, rather than
  asking each module to remember to check. This is the core fix.
- **Intents are explicit bus events on `volition.out`.** Schema:
  `{kind: "speak"|"think"|"act", about: <entry_id or summary of the coalition
  content>, effector?: <name>, params?: {...}}`. Putting intents on the bus keeps
  them auditable (Praxis already audits; evaluation can observe) and decouples
  the decision from the effectors. `volition.out` joins the canonical producer
  set and the config stream-wiring test.
- **Effectors subscribe to intents and realize them.** Lingua runs a dedicated
  intent-subscription loop (the pattern Audio Out already uses to subscribe to
  `lingua.external`/`thymos.out`): on a `speak` intent it calls `speak(...)`
  using the referenced conscious content as the prompt; on a `think` intent it
  calls `think(...)`. Praxis on an `act` intent dispatches to the named effector.
  Effectors lose any self-trigger (`on_workspace` reflexes).
- **v1 policy: minimal, real, pluggable.** Default `ActionSelectionPolicy`:
  given a non-inhibited snapshot, emit a single `speak` intent when the conscious
  coalition contains an event the entity is communicatively disposed toward
  (e.g. a user-communication event) — with a one-in-flight guard so the entity
  finishes one utterance before forming another intent. The policy object is
  injectable so `drives-to-behavior` can supply a richer one (drive activation
  biasing whether/what to speak or act) without touching Volition's plumbing.
- **Half-duplex / feedback safety lives in the policy + intent loop**, not in
  Lingua: the policy will not form a `speak` intent about the entity's own prior
  output, and the in-flight guard prevents stacking. (Acoustic echo cancellation
  remains an audio-layer concern, out of scope.)

## Risks / Trade-offs

- [Volition becomes a hidden second executive that drifts from Syneidesis] →
  keep it thin and verdict-consuming: it never re-decides salience/inhibition,
  only acts on Syneidesis's snapshot. Documented single responsibility.
- [Over- or under-speaking from a naive v1 policy] → policy is injectable and
  conservative by default (one intent, disposition-gated, in-flight guard);
  tuning is a follow-up with drives. Tests pin the default behavior.
- [Coupling the cycle to effectors] → avoided: the cycle invokes Volition (pure:
  snapshot → intents → publish); effectors consume intents off the bus. No
  direct cycle→effector calls.

## Migration Plan

Additive. Existing modules keep working; the change adds Volition + a stream +
intent-subscription loops, and removes effector self-triggers (Lingua had none
on `main` after the reflexive change was reverted; Praxis is already
method-only, now formalized to require an intent). Rollback = revert the branch.
No data migration. No live boot required to validate (unit tests with fakes).

## Open Questions

- Should Volition eventually be promoted to a named module in the taxonomy, or
  stay a cycle-level executive function? (Proposed: stay thin for now.)
- Exact default policy disposition — respond to all user-communication events,
  or require a minimum coalition salience / a communicative drive? (Proposed:
  disposition-gated + in-flight guard now; drive-gated in `drives-to-behavior`.)
- `think` (internal speech) trigger policy — deliberate on high-salience
  non-communicative coalitions? (Proposed: define the `think` intent now, leave
  its policy minimal/opt-in pending review.)
