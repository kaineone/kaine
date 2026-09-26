## 1. Runner

- [x] 1.1 Read `<bundle>/manifest.json` after a successful preservation when Phantasia is in the step's module set; map a false flag to `failed:world_model_not_captured` and a missing or unreadable manifest to `failed:manifest_unreadable`.
- [x] 1.2 Record `world_model_captured` (true, false, or null) on every step.

## 2. Verification

- [x] 2.1 Tests: captured, not captured, missing manifest, and a step without Phantasia whose bundle has no manifest still completes.
- [x] 2.2 Offline suite green; `openspec validate ignition-world-model-check --strict`.
