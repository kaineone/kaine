## 1. Gate

- [x] 1.1 `config.py`: optional `hardware` table (`welfare_acknowledgement`, `ethics_reference`); record whether `data_source` was set explicitly.
- [x] 1.2 `plugin.py`: the gate for `target = "hardware"`, one message naming every unmet condition; WARNING on every hardware boot naming the ethics reference.
- [x] 1.3 `session.py`: refuse `target = "hardware"` when `cl.is_simulator()` is true; register no simulator data source on hardware.

## 2. Freeze safety and visibility

- [x] 2.1 Broker: discard queued stimulation when a beat arrives more than two periods after the previous one, and log it.
- [x] 2.2 Broker: cap the real-time open-window spike buffer to the most recent window length.
- [x] 2.3 Broker: count and WARN on real-time beats that arrive before the previous boundary was consumed.

## 3. Tests

- [x] 3.1 Each gate condition, alone and together; the complete gate declares seams and logs the WARNING.
- [x] 3.2 A stubbed SDK reporting the simulator makes a hardware session refuse; one reporting hardware lets it open (no real device used).
- [x] 3.3 Freeze and resume discards stale stimulation; the spike cap holds during a long gap; overrun counting.

## 4. Docs

- [x] 4.1 `docs/cl1.md`: "Running on a CL1" for owners.
- [x] 4.2 `docs/biological-welfare.md`: point to the gate and state what it cannot verify.
