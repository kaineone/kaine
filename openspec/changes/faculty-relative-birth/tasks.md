## 1. Implementation

- [x] 1.1 `Faculties` and the faculty-relative C2 in `maturation_gate.py`; `decide_birth` skips the embodiment guard without Mundus (reason `born_into_perceptual_world`); the birth payload records the world and the applied conditions.
- [x] 1.2 The gate runner reads the faculties from its registry, passes them through, and records them in its status.
- [x] 1.3 `docs/operations.md` (gestation section): birth into the perceptual world, and which conditions apply.

## 2. Verification

- [x] 2.1 Tests: every faculty combination for C2 (none, Hypnos only, Phantasia only, both); a base-thesis registry is born into its perceptual world when C1 and C3 hold; with Mundus enabled but unreachable it still holds awaiting embodiment; the payload and status record the world and the conditions; default `Faculties` keeps today's behaviour.
- [x] 2.2 Offline suite green; `openspec validate faculty-relative-birth --strict`.
