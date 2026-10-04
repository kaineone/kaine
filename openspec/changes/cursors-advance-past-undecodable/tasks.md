## 1. Consumers
- [x] 1.1 Module loops read with `read_entries` and advance to the last scanned id: Chronos (user input, Hypnos), Eidolon (voice, Thymos, Nous, Hypnos), Empatheia, Lingua (self-model, intents), Mnemos, Mundus (intents, speech), Nous, Perception, Phantasia, Praxis, Soma (Hypnos), Thymos, Topos (Hypnos) and Vox.
- [x] 1.2 Chronos records an interaction only for a decoded event.
- [x] 1.3 Gestation's Soma and Topos readers advance past undecodable batches.
- [x] 1.4 The Nexus bridge protocol and loop use `read_entries`. So do the remote bridge's transcript and affect loops.

## 2. Tests
- [x] 2.1 A static guard: no `bus.read(` under `kaine/` outside the bus and the two one-shot readers.
- [x] 2.2 The Nexus bridge delivers an event written after more undecodable entries than one read returns.
- [x] 2.3 Gestation's Soma reader records a report written after more than one read's worth of undecodable entries.
- [x] 2.4 The gestation-owner and Nexus-bridge test fakes, which served only `read`, gain `read_entries`.
