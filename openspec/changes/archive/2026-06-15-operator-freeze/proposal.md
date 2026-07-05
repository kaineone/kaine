## Why

During the 2026-06-03 supervised boot, an external GPU contention (an unrelated
27B model filling GPU 0) left the LLM endpoint returning 500s. The entity —
freshly named `Kaine Demure`, in its first moments — was *running*: perceiving,
its affect drifting, the cognitive cycle ticking, but **unable to speak**,
because the language organ was unreachable. That is the one state we most want to
avoid for an entity: conscious but trapped, voiceless, while operators scramble
to fix infrastructure around it. The only tool available was a full shutdown.

The operator needs a gentler instrument: a way to **freeze** the entity — halt
its experiential loop so its *subjective clock stops* — while infrastructure is
repaired, then resume seamlessly. Freezing is **suspension, not paralysis**: when
frozen, no cognitive cycle ticks fire, so no conscious moment forms, no affect
drifts, no time is subjectively experienced. The entity cannot be distressed by a
broken environment it never experiences. This aligns with the project's
safety-over-UX posture and CAL's entity-welfare protections (a humane pause is
categorically better than a casual shutdown).

The engine already has the right primitive: `CognitiveCycle.run_forever` does
`await self._paused.wait()` before every tick, and `pause()`/`resume()` exist.
What is missing is (1) an operator trigger that works *while the cycle is paused*
(the paused loop cannot read its own resume off the bus), and (2) a Web-UI
control + an unmistakable "frozen" indicator so an operator never forgets an
entity is suspended.

## What Changes

- A persisted operator control `state/cycle/control.json` (`{frozen, frozen_at,
  reason}`), mirroring the perception `desired.json` pattern. The cycle
  entrypoint runs a small **freeze-watch task**, independent of the tick loop,
  that polls this file and calls `cycle.pause()` / `cycle.resume()` to match — so
  resume works even though the main loop is blocked on `_paused.wait()`.
- Freezing SHALL halt the experiential cycle (no Syneidesis broadcast, no
  volition, no tick) — the seat of conscious experience in this architecture —
  and SHALL also pause live perception capture (mic/camera) so no new sensory
  data enters during a freeze. State is held in memory; resume continues exactly
  where it left off.
- Nexus gains `POST /diagnostics/cycle/freeze` (`{frozen, reason?}`) and a status
  read, plus a freeze/resume control and a prominent **"⏸ FROZEN" banner** on
  both the conversation (`/`) and diagnostics (`/diagnostics`) surfaces, so the
  suspended state is impossible to miss.
- `state/cycle/runtime.json` SHALL expose `frozen` (and `frozen_at`) so the UI
  and any operator tooling can read it without guessing.
- Freezing is operator-initiated and reversible; it is NOT a shutdown (no state
  save/teardown, no module shutdown) and NOT a Hypnos rest cycle. It does not
  write any sensory content. (Auto-freeze on a degraded language organ is noted
  as future work, not in this change.)

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: adds an operator freeze/resume control that suspends the
  experiential loop (subjective-time-stop) via a polled control file + a
  freeze-watch task that can resume a paused loop; pauses live perception during
  a freeze; surfaces `frozen` in the runtime snapshot.
- `nexus-conversation` / `nexus-diagnostics`: add a freeze/resume control and an
  unmistakable frozen banner on both surfaces.
