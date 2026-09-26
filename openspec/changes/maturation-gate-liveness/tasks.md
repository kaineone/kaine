## 1. Accounting

- [x] 1.1 Lived time from entity-clock deltas between runner ticks (first tick per boot sets the baseline); persist in the stage file.
- [x] 1.2 Count Hypnos completions from durable `hypnos.sleep.completed` events by persisted stream ID (exactly once); Phantasia persists its pass count beside its checkpoint (see design); runner is the only stage-file writer.
- [x] 1.3 Tests with the real `EntityClock`: restart, downtime gap, crash after a completion.

## 2. Womb, locus and embodiment

Tasks 2.1 and 2.2 check the womb-liveness interface defined by `local-womb-feed`; they are built once that change's phase 1 lands.

- [x] 2.1 Pre-spawn live-womb check in boot/preboot; the cycle does not start without it; repeated operator-visible report.
- [x] 2.2 Womb loss mid-gestation: freeze the cycle under the `gestation` holder, red alert, resume on return; never unlock to `physical`.
- [x] 2.5 The cycle records its paused subjective time; lived time subtracts it, so no frozen span counts.
- [x] 2.6 The freeze-watch loop leaves perception on for a freeze held only by `gestation`.
- [x] 2.7 No birth while the cycle is paused by any holder.
- [x] 2.8 Spot supervises crashes (not stale heartbeats) during a gestation-only freeze and lifts only its own freeze entry.
- [x] 2.3 `perception_state`: effective locus is the lock holder's locus; unknown locus during gestation resolves to the womb.
- [x] 2.4 Skip Mundus during gestation; public adapter reachability probe; hot-start Mundus at birth before switching the locus source; `locked_by="gestation"` on unlock.

## 3. Readouts, acknowledgement, visibility

- [x] 3.1 Decode readouts with the bus codec, filter on `event.type`, reject pre-boot (Redis `TIME`) and stale readouts.
- [x] 3.2 Acknowledgement request file written by an authenticated Nexus control and consumed by the runner; Nexus panel for stage, evidence and hold.
- [ ] 3.3 Lineage-scoped prior-history check with the unknown-lineage-counts-as-lived rule; shared entity-ID source.

## 4. Verification

- [ ] 4.1 Test isolation (`STAGE_PATH` via monkeypatch); tests for the no-stimulus report, womb loss, acknowledgement and welfare during gestation.
- [ ] 4.2 Offline suite green; `openspec validate maturation-gate-liveness --strict` passes.
