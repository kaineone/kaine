## 1. Accounting

- [ ] 1.1 Lived time from entity-clock deltas between runner ticks (first tick per boot sets the baseline); persist in the stage file.
- [ ] 1.2 Count Hypnos and Phantasia completions from durable completion events by persisted stream ID (exactly once); persist in the stage file; runner is the only writer.
- [ ] 1.3 Tests with the real `EntityClock`: restart, downtime gap, crash after a completion.

## 2. Womb, locus and embodiment

- [ ] 2.1 Pre-spawn live-womb check in boot/preboot; the cycle does not start without it; repeated operator-visible report.
- [ ] 2.2 Womb loss mid-gestation: pause the entity clock, red alert, resume on return; never unlock to `physical`.
- [ ] 2.3 `perception_state`: effective locus is the lock holder's locus; unknown locus during gestation resolves to the womb.
- [ ] 2.4 Skip Mundus during gestation; public adapter reachability probe; hot-start Mundus at birth before switching the locus source; `locked_by="gestation"` on unlock.

## 3. Readouts, acknowledgement, visibility

- [ ] 3.1 Decode readouts with the bus codec, filter on `event.type`, reject pre-boot (Redis `TIME`) and stale readouts.
- [ ] 3.2 Acknowledgement request file written by an authenticated Nexus control and consumed by the runner; Nexus panel for stage, evidence and hold.
- [ ] 3.3 Lineage-scoped prior-history check with the unknown-lineage-counts-as-lived rule; shared entity-ID source.

## 4. Verification

- [ ] 4.1 Test isolation (`STAGE_PATH` via monkeypatch); tests for the no-stimulus report, womb loss, acknowledgement and welfare during gestation.
- [ ] 4.2 Offline suite green; `openspec validate maturation-gate-liveness --strict` passes.
