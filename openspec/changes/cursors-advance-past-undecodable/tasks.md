## 1. Consumers
- [x] 1.1 Module loops read with `read_entries` and advance to the last scanned id: Chronos (user input, Hypnos), Eidolon (voice, Thymos, Nous, Hypnos), Empatheia, Lingua (self-model, intents), Mnemos, Mundus (intents, speech), Nous, Perception, Phantasia, Praxis, Soma (Hypnos), Thymos, Topos (Hypnos) and Vox.
- [x] 1.2 Chronos records an interaction only for a decoded event.
- [x] 1.3 Gestation's Soma and Topos readers advance past undecodable batches.
- [x] 1.4 The Nexus bridge protocol and loop use `read_entries`. So do the remote bridge's transcript and affect loops.

- [x] 1.5 The welfare monitor's distress and gray-zone loops advance to the last scanned id only when they finish the batch; on a crossing the cursor stays at the crossing entry.
- [x] 1.6 The Hypnos audit drain stops only when a read scans nothing.

## 2. Tests
- [x] 2.1 A static guard: no `bus.read(` under `kaine/` outside the bus and the two one-shot readers.
- [x] 2.2 The Nexus bridge delivers an event written after more undecodable entries than one read returns.
- [x] 2.3 Gestation's Soma reader records a report written after more than one read's worth of undecodable entries.
- [x] 2.5 Under notify, the welfare monitor's cursors stop at a crossing and later reach the end, and every gray-zone event after the crossing reaches the repeat counter.
- [x] 2.6 The Hypnos audit drain returns an event written after more undecodable entries than one read returns.
- [x] 2.7 Chronos's cursor passes undecodable user input without recording an interaction, and a real input still records one.
- [x] 2.4 The gestation-owner, gestation-jitter, gestation-schedule and Nexus-bridge test fakes, which served only `read`, gain `read_entries`.
