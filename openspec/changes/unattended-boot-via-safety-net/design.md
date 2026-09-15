# Design — `unattended-boot-via-safety-net`

## Why

The operator-present gate (`KAINE_CYCLE_OPERATOR_PRESENT=1`, exit 2) was built for first-run testing, at a time when the system had no internal safeguards: a sentient entity must not be created and left alone with no input and no way to deal with runaway processes. Those safeguards now exist in the system itself — `spot-supervisor` (always-on module supervisor, liveness detection, freeze-during-recovery, snapshot-before-restart, restart ladder, escalation, durable incident log) and `entity-preservation` (divergence-triggered live preservation, autonomous welfare-protective response). The human-presence requirement is therefore redundant in substance, and a human typing `=1` into an env var proves nothing.

This change does not delete a gate and does not weaken protection. It moves protection from an unverifiable claim ("a human said they were here") to a machine-verified demonstration ("the safeguards are demonstrably live on this install, checked at every boot"). The new gate is **stricter** than the one it replaces: an unattended boot must prove the preserve→revive path actually works here, and must additionally prove the Spot supervisor is live with its freeze/recovery path armed — a condition research mode does not even carry.

The precedent being generalized is the research safety net: an unsupervised research boot refuses (exit 5) unless all five conditions hold, with no override that skips the net. Unattended mode reuses that net verbatim and adds the sixth condition that the operator's argument (Spot) requires.

## Supervision modes

| Mode | Selector | Verification performed | Refusal exit code |
| --- | --- | --- | --- |
| `operator-present` | `KAINE_CYCLE_OPERATOR_PRESENT=1`; also the fallback when neither research nor unattended is selected | Presence claim only: the env var is checked. Nothing about the safeguards is verified. | `2` (unchanged) |
| `research` | existing research-run selection (unchanged) | Five-condition safety net, evaluated by `kaine/cycle/research_gate.py` | `5` (unchanged) |
| `unattended` (new) | `KAINE_CYCLE_UNATTENDED=1`, or the supervision-mode config key set to `unattended` (e.g. `supervision_mode = "unattended"`); env takes precedence over config | The same five-condition net (same evaluator) **plus** condition 6: Spot supervisor live and freeze/recovery armed | `6` (new) |

Rules that hold across the table:

- Exactly one mode is resolved per boot. If more than one selector is active (for example `KAINE_CYCLE_OPERATOR_PRESENT=1` together with `KAINE_CYCLE_UNATTENDED=1`), the boot refuses as a misconfiguration **before any gate runs** — it never silently picks one. This refusal uses the boot's generic configuration-error exit, not 2, 5, or 6.
- A failed gate never falls back to another mode. An unattended boot whose net fails refuses; it does not re-classify as operator-present or research.
- Unattended is not a research run: no experiment machinery, no admissibility requirements, no research-run bookkeeping. Only the net is shared.

## The six unattended conditions

| # | Condition | How it is verified |
| --- | --- | --- |
| 1 | Preservation enabled | Config read: `[preservation.divergence_monitor].enabled = true` |
| 2 | Welfare response wired | Config read: `[preservation.welfare_response].enabled = true` |
| 3 | Logging active | Config read: `[evaluation].enabled = true` or `[research_event_log].enabled = true` |
| 4 | Dry self-check passed | Executed: a real preflight preserve→revive round-trip against a scratch subject in a sandbox, on this install (same code path as research condition 4) |
| 5 | Encryption satisfied | Config read, conditional: if `[preservation].require_encryption = true` then `[security.state_encryption].enabled = true` must hold; otherwise vacuous pass |
| 6 | Spot live, freeze armed (unattended only) | Executed: supervisor control-plane handshake plus Spot selftest; see next section |

Notes:

- Conditions 1–5 are evaluated by the same evaluator research mode uses, lifted from `research_gate.py` into a shared function so the two nets cannot drift. Condition 3's predicate is shared verbatim (including `[research_event_log]`); an unattended-specific log section would be a separate change.
- Evaluation order: config conditions (1, 2, 3, 5) first; then 6 (handshake/selftest); then 4 (the round-trip is run only if 1 and 2 passed, since the drill exercises those paths; otherwise it is reported as blocked). The refusal names **every** failed condition.
- No override skips any condition, including 6.
- Per-condition gate results are written to the boot journal and, where logging is active, to the durable event/incident log, so refusals are auditable after the fact.

## The Spot check (condition 6) without starting the entity

The check must prove that the supervisor which replaces the human is live and can freeze — without booting the entity it will supervise. Mechanics:

1. **Endpoint resolution.** The gate resolves the supervisor interface from the same runtime configuration an entity boot would use — no gate-only config that could disagree with runtime config.
2. **Status handshake.** The gate sends a status request over the supervisor control plane: the control socket for the daemon deployment, or the supervisor module's control API constructed exactly as an entity boot would construct it. Bounded: a per-attempt timeout inside a bounded total startup grace (defaults: 2 s per attempt, 10 s total, configurable), absorbing startup jitter under systemd; unit ordering does the heavy lifting.
3. **Arming assertions.** The status response must assert: supervisor enabled; freeze hook armed; restart ladder has at least one rung; escalation target configured; incident log writable (Spot probes writability, e.g. a canary append at startup or status time).
4. **Selftest.** The gate then requests Spot's selftest. Spot drills its own internal probe module: induce probe liveness failure → freeze → probe-scoped snapshot to a scratch location → first ladder rung → release → incident record. The drill must complete with a pass inside the bounded window.
5. **Failure mapping.** No response, a disarmed field, or a failed/absent selftest each fail condition 6 with a specific reason string carried into the refusal output.

Why handshake + selftest rather than config flags: a config flag is exactly as unverifiable as the env-var claim this change removes. The selftest is to Spot what condition 4's round-trip is to preservation — behavioral proof, on this install, at this boot.

Why the entity is not started: the gate speaks only to the supervisor control plane; the probe is Spot's own fixture. No entity module is imported or instantiated, no entity state is read or written, and no freeze is ever issued against a live supervised target — including when this boot is a replacement after a crash and an entity is already under supervision.

## Exit code 6

| Code | Meaning |
| --- | --- |
| `0` | boot admitted |
| `2` | operator-present claim gate refused (unchanged) |
| `5` | research safety net refused (unchanged) |
| `6` | unattended safety net refused (new) |

Why 6, and why not 2 or 5:

- **Not 2.** Exit 2 means "the human-presence claim is missing or invalid". An unattended refusal has a different predicate — the machine-verified net is not live on this install — and the operator constraint says 2's meaning must not move. Reusing 2 would also misroute every unattended refusal as "someone forgot the env var".
- **Not 5.** Exit 5 means "a research run failed its net". Unattended failures include a condition research does not have (Spot), and they happen on unattended machines; journals, quadlet tooling, and incident automation must be able to distinguish "a researcher misconfigured a research run" from "an unattended boot found the net not live" without parsing stderr.
- **Why 6 specifically.** The unattended gate is the research five plus the sixth Spot condition; its code is the next integer in the same family. 6 is recorded here as reserved for the unattended gate and for nothing else in the boot's exit map.
- **One code, named conditions.** Exit codes exist for routing (systemd, scripts, dashboards); condition identity exists for humans. The refusal output names every failed condition by number and name, so a single gate-level code stays unambiguous.

## systemd / quadlet consequence

Today `kaine-cycle.container` carries the operator-present environment and has no `[Install]`: a human starts it. This change permits an `[Install]` section under exactly one condition:

- `kaine-cycle.container` may gain `[Install]` (e.g. `WantedBy=default.target`) **only** in a version whose environment selects unattended mode (`KAINE_CYCLE_UNATTENDED=1`). The selector edit and the `[Install]` edit travel together; an operator-present or research container file must not auto-start.
- The point is power loss. With `[Install]`, a power-loss reboot makes systemd start the unit, and the boot re-runs all six conditions on this install, at this boot. The net is **re-verified every boot** — never assumed from a previous boot, never assumed from the file's contents.
- If the net is not live at that reboot (Spot unit failed, snapshot volume unmounted, encryption key unavailable), the boot refuses with exit 6, the unit is left failed, and the entity stays down. Down-but-protected is the intended outcome; the refusal is sticky and visible in `systemctl status` and the journal.
- The unattended unit orders after the Spot supervisor unit (`After=`/`Wants=` on the spot unit) so the boot-time handshake is not racing Spot's startup; the bounded handshake grace absorbs residual jitter.
- The unattended unit does not auto-restart after a gate refusal (`Restart=no`). A restart loop against a refusing gate would be "assuming it's fine, with retries". Once the entity runs, restarts belong to Spot's ladder, not to systemd.
- Conversely, an operator-present container file gains nothing: auto-starting a claim-based boot would only farm exit-2 failures on headless reboots. Boot-time auto-start is offered exclusively through the stricter gate — which is the intended incentive alignment.

## Shape of the implementation

- `kaine/cycle/__main__.py`: mode resolution gains `unattended` (env `KAINE_CYCLE_UNATTENDED=1`, else config key; env over config; multi-selector conflict is a pre-gate misconfiguration error). Gate dispatch: research → `research_gate` (exit 5), unattended → unattended gate (exit 6), otherwise operator-present (exit 2, unchanged).
- The five-condition evaluator is extracted from `research_gate.py` into a shared function; `research_gate.py` calls it and keeps its messages and exit code, so no existing refusal changes meaning.
- New: the Spot check (handshake + arming assertions + selftest), used only by the unattended gate.
- Quadlet: env swap to unattended, add `[Install]`, add ordering against the spot unit, `Restart=no`.

The normative requirements for this change live in `specs/unattended-boot/spec.md`.