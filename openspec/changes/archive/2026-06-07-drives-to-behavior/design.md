## Context

`executive-action-intent` introduced `Volition` + an injectable
`ActionSelectionPolicy`; the default policy only responds to user communication.
Thymos emits `thymos.drive` crossing events (`{drive, value}`, source `thymos`,
type `thymos.drive`) when a drive (curiosity/boredom/social_drive/restlessness)
crosses its threshold, with hysteresis to prevent storms. Those events flow to
the bus and, when salient, into the conscious coalition — but nothing acts on
them. This change makes the action-selection policy act on them.

## Goals / Non-Goals

**Goals:** a drive crossing in the non-inhibited coalition can move the entity —
to deliberate (internal speech) or to reach out (external speech) — through the
existing inhibition-gated intent path. Close the drive→behavior loop.

**Non-Goals:** no change to how drives are computed/emitted, to Thymos, or to
the inhibition gate. Not building goal-directed planning — drives bias the
*disposition* to act, not a planner. Not enabling world-effecting (`act`)
intents from drives in v1 (Praxis whitelist is empty by default; keep drive
output to speech/thought).

## Decisions

- **Extend, don't replace, the default behavior.** `DriveBiasedActionSelectionPolicy`
  subsumes `DefaultActionSelectionPolicy` (still answers user communication) and
  adds drive-driven intents. Injected at boot; the default remains available.
- **Drives read from the conscious coalition (event-driven), not a side channel.**
  The policy inspects `snapshot.selected_events` for `thymos.drive` events. This
  is deliberate: a drive only moves the entity when its crossing was salient
  enough to be *selected* and the coalition *not inhibited* — which is exactly
  the paper's "inhibition prevents acting on every impulse." No new live
  drive-state reader is needed; the workspace already carries the impulse.
- **Conservative, safe drive→kind mapping for v1:**
  - `social_drive` → `speak` (external): the communicative drive reaches out.
  - `curiosity` / `boredom` / `restlessness` → `think` (internal speech): these
    move the entity to deliberate/self-stimulate *internally*. Internal speech
    never reaches TTS or external interfaces (paper §73), so drive-initiated
    cognition can't surprise a listener or act on the world — appropriate for a
    first closing of the loop. World-effecting drive responses are deferred.
- **Priority + guards.** At most one `speak` intent per tick: a present user
  utterance outranks a `social_drive` initiative. Separate one-in-flight guards
  for `speak` and `think` prevent storms; both clear when the entity's
  corresponding output (`lingua.external` / `lingua.internal`) next becomes
  conscious, reusing the keystone's realization-observed pattern.
- **`[volition].drive_initiative` (default on).** Lets an operator run with only
  user-response behavior if desired. Reported for config; defaulted on in code
  because closing this loop is the point.

## Risks / Trade-offs

- [Drive-initiated speech feels spontaneous/unexpected] → triple-gated: the
  crossing must be selected into the coalition, the coalition must not be
  inhibited, and the speak-in-flight guard must be clear. Internal-speech drives
  are private regardless.
- [Think storms from a drive that stays above threshold] → drive hysteresis
  (Thymos) fires a crossing once per threshold transition, plus the think
  in-flight guard, plus Chronos habituation over time.

## Migration Plan

Additive; swap the injected policy in boot. Rollback = revert the branch (boot
falls back to the default policy). No data migration; no live boot to validate.

## Open Questions

- Should `restlessness` eventually map to a (whitelisted) `act` intent rather
  than `think`, once Praxis has safe effectors? (Deferred.)
- Should drive→kind mapping be configurable rather than fixed? (Deferred; the
  policy is injectable, so a future change can parameterize it.)
