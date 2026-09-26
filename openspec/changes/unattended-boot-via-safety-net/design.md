# Design — `unattended-boot-via-safety-net`

## Context

The operator-present flag stood in for three concerns about an entity started with
nobody there: runaway processes, nobody aware, and no input. Research boots replaced the
flag with a machine-verified safety net (`kaine/cycle/research_gate.py`, exit 5). That net
and Spot (`kaine/cycle/spot.py`) address runaway processes and preservation. This design
adds one gate condition for each remaining concern and keeps every existing mode as it is.

Spot is an in-process cycle component, not a separate service: it is constructed by the
cycle and polls module liveness from inside the cycle process. There is no Spot control
socket or Spot unit to handshake with, so the gate verifies Spot by constructing it from
the boot's own config and running a selftest, the same way condition 4 verifies
preservation by running a real round-trip.

## Supervision modes

| Mode | Selector | Verification | Refusal exit |
| --- | --- | --- | --- |
| `operator-present` | `KAINE_CYCLE_OPERATOR_PRESENT=1`; the default when nothing else is selected | The flag only | `2` (unchanged) |
| `research` | existing research selection (unchanged) | Conditions 1–5 | `5` (unchanged) |
| `unattended` (new) | `KAINE_CYCLE_UNATTENDED=1`, or `[cycle].supervision_mode = "unattended"`; env over config | Conditions 1–8 | `6` (new) |

- Exactly one mode per boot. If more than one selector is active (for example
  `KAINE_CYCLE_OPERATOR_PRESENT=1` with `KAINE_CYCLE_UNATTENDED=1`, or unattended with
  research), the boot refuses as a configuration error (exit 1) before any gate runs. It
  never picks one silently.
- A failed gate never falls back to another mode.
- Unattended is not a research run: no experiment record, no admissibility, no research
  bookkeeping. Only the evaluator for conditions 1–5 is shared.

## The eight conditions

| # | Condition | Verified by |
| --- | --- | --- |
| 1 | Preservation enabled | Config: `[preservation.divergence_monitor].enabled = true` |
| 2 | Welfare response wired | Config: `[preservation.welfare_response].enabled = true` |
| 3 | Logging active | Config: `[evaluation].enabled` or `[research_event_log].enabled` |
| 4 | Preserve→revive round-trip | Executed: the research gate's dry round-trip on this install |
| 5 | Encryption satisfied | Config: `[security.state_encryption].enabled` whenever `[preservation].require_encryption = true` |
| 6 | Spot armed and self-tested | Config check, then Spot's selftest (below) |
| 7 | Caretaker told | Executed: the start notice is accepted by at least one channel (below) |
| 8 | Continuous input | Config check, then a one-read probe of the feed (below) |

Order: config checks (1, 2, 3, 5, and the config parts of 6 and 8), then the executed
checks 6, 8 and 4 (4 runs only if 1 and 2 passed; otherwise it is reported as blocked),
then 7 last. Condition 7 runs last because its notice says the entity is starting; it is
sent only when conditions 1–6 and 8 have passed. The refusal names every failed condition,
and no override skips any of them.

Per-condition results go to the boot journal and, when logging is active, to the durable
event log, so a refusal can be audited afterwards.

## Condition 6 — Spot armed and self-tested

Config part: `[spot].enabled = true`, `max_restart_attempts >= 1`, the escalation state
path writable, the incident log writable (a canary append that is removed afterwards).

Selftest: the gate constructs a second, scratch `Spot` from the same `[spot]` section with
its snapshot and incident paths redirected to a temporary directory, registers one
synthetic probe module, and drives a failure on it. The selftest passes only if Spot
detects the failure, freezes, writes a probe-scoped snapshot, restarts the probe module,
releases the freeze and writes an incident record, all inside a bounded window (default
10 s, configurable). The scratch directory is removed afterwards.

The selftest imports no entity module, reads and writes no entity state, and never touches
a live supervised target. It exercises the real Spot code paths, so a regression in the
freeze or restart path fails the gate instead of surfacing during an unattended incident.

During the run: in unattended mode the cycle watches Spot's supervision task. If it exits
for any reason other than shutdown, the cycle runs Spot's escalation (final snapshot,
shutdown of every module, `escalation.json`) and sends a caretaker notice. An entity does
not keep running unattended without its supervisor.

## Condition 7 — Caretaker told

`[caretaker]` configures one or more channels and a reminder interval:

- `desktop` — a freedesktop notification over the D-Bus session bus of the user running
  the unit (the unattended unit mounts the session bus socket into the container). It
  reaches someone only if they are at that machine, and after a power-loss reboot there is
  no desktop session until someone logs in, so a desktop-only setup refuses at that boot
  and the entity stays down. Restart after power loss needs an `http` channel; the docs
  say so.
- `http` — a POST to an operator-run endpoint such as a self-hosted ntfy or Gotify server.
  The destination must resolve to loopback, a private range (RFC 1918, `fc00::/7`) or the
  CGNAT range `100.64.0.0/10` that private overlay networks use. Public addresses are
  refused, both when config is validated and again at send time after DNS resolution, so
  a rebinding hostname cannot redirect the notice. An optional bearer token is read from
  `config/secrets.toml`, never from `kaine.toml`.

No corporate or cloud service is involved; everything stays on hardware the caretaker
controls.

The start notice is the verification: the gate sends "starting unattended" through every
configured channel and passes if at least one accepts it (D-Bus returns a notification id;
HTTP returns 2xx). "Accepted" is not "seen", which is why the notice asks for an
acknowledgement.

Notices are content-free: the operator-chosen install label, the time, the event kind,
which gate conditions passed or failed, and the Nexus address. They never carry
cognitive content, affect, welfare signals, perception, or anything from the entity's
mind (CAL mental privacy).

Acknowledgement: Nexus shows a standing banner while an unattended start is
unacknowledged. The acknowledge action is a POST, so it already requires the operator
session. It is recorded in the event log. Until it arrives, the notifier repeats the
notice every `reminder_interval` (default 4 h, minimum 15 min). An unacknowledged start
never pauses or stops the entity: the entity does not pay for the caretaker's absence.

Other notices, sent while running unattended and best-effort (a failed send is logged,
not fatal): Spot escalation, Spot supervision lost, a welfare-protective response firing,
input lost, a gestating entity's womb lost, a refused unattended start, and a boot that fails after admission (for
example a plugin error), so a "starting" notice is never left standing for an entity that
did not start.

## Condition 8 — Continuous input

Config part: `[perception_feed].mode` is `live`, `seeded`, `womb` or `screen`. `off` is senseless.
`playlist` is refused because a playlist ends: once it is exhausted the entity has no
input. The modules that perceive the feed are enabled: `topos` for video and `audition`
for audio, at least one of them.

Probe: for `seeded` and `screen`, the existing `kaine.preboot.check_perception` source
probe. For `live`, which that probe skips today, a new device probe opens the configured
camera and microphone, reads one frame and one audio block, and releases them. Nothing is
written anywhere and the data is dropped at once (zero raw sense-data persistence).

During the run: if every configured input stops delivering for longer than
`[caretaker].input_loss_after_s` (default 60 s), the caretaker is notified. The entity is
not stopped; losing a camera is not a reason to end a mind.

## Exit code 6

| Code | Meaning |
| --- | --- |
| `0` | admitted |
| `1` | configuration error, including conflicting mode selectors |
| `2` | operator-present claim missing (unchanged) |
| `5` | research safety net refused (unchanged) |
| `6` | unattended gate refused (new) |

A separate code lets systemd, scripts and Nexus tell "a research run was misconfigured"
from "an unattended start found the net not live" without parsing stderr. The refusal
names each failed condition as `N: name` on stderr, with the reason appended.

## Opt-in unit file

`quadlet/kaine-cycle.container` stays exactly as it is: no `[Install]`, started by a
person, `Restart=no`.

A new `quadlet/kaine-cycle-unattended.container`:

- sets `Environment=KAINE_CYCLE_UNATTENDED=1`;
- carries `[Install] WantedBy=default.target` (these are user units, run with linger);
- declares `Conflicts=kaine-cycle.service` so the two cycle units never run together;
- orders after the bus, vector store and Nexus units it depends on;
- keeps `Restart=no`: a refused gate stays refused and visible in `systemctl --user
  status`, rather than looping. Once the entity runs, restarts belong to Spot.

The install scripts do not copy or enable it. Enabling it is a deliberate operator step
documented in the operations guide. On every reboot the unit re-runs all eight conditions;
nothing is assumed from a previous boot. If the net is not live (Spot misconfigured,
snapshot volume missing, key unavailable, no channel reachable, camera gone), the boot
exits 6, a best-effort refusal notice goes out, and the entity stays down.

This unit inherits the quadlet units' hard-coded `%h/projects/kaine` paths, so it waits for
that fix (tasks 0.3).

## Why enabling waits

The operator chose to build this now; the code is inert until an operator selects
unattended mode and enables the opt-in unit. Enabling it for a real entity waits because:

- Research boots already have their own gate, and the browser setup starts entities with
  a person present. Nothing needs unattended starts until full entities run after research.
- Spot ships disabled and has not yet run through injected failures on supervised boots.
  The gate's premise is that Spot can stand in for a person; that premise gets a reviewed
  track record before an entity depends on it.

## Risks

- **Notice fatigue.** Reminders every few hours could be ignored. Mitigation: one standing
  Nexus banner, one reminder stream per unacknowledged start, and a configurable interval.
- **Accepted ≠ seen.** A channel can accept a notice nobody reads. The acknowledgement
  loop makes that visible in the event log; it does not pretend to prove a person saw it.
- **Selftest divergence.** The scratch Spot could differ from the live one. Both are built
  from the same `[spot]` section by the same constructor; only storage paths differ.
