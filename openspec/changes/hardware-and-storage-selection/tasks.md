## 1. Hardware inventory and consent
- [x] 1.1 A per-device consumer probe in `kaine/hardware.py`: processes and used memory per device where visible, and an explicit "not visible" marker otherwise. It must never raise.
- [ ] 1.2 Wizard inventory step, listing all backends the probe recognises, plus CPU cores and system memory. Written as a step in the shared step model (`browser-first-run`), and rendered by the terminal driver.
- [ ] 1.3 `[hardware].allowed_devices` and `[hardware].cpu_threads`: config shape validation, and the wizard consent step.
- [x] 1.4 `resolve_device` honours the allowed set; `KAINE_FORCE_DEVICE` is logged as an override. Tests: an excluded GPU, no section, the force override.
- [ ] 1.5 Fit-checked proposals, using free memory and, when present, the residency footprint catalogue. They offer alternatives when a proposal does not fit.

## 2. One device map
- [ ] 2.1 The wizard writes the device map once, and generates the compose GPU variables and the native launcher settings from it.
- [ ] 2.2 A pre-boot row that fails when the compose variables or service launchers disagree with the device map.

## 3. Shared services
- [ ] 3.1 `[services.<name>].shared`, asked for each detected service; config shape validation.
- [ ] 3.2 A source-guard test: no code path stops, restarts or evicts a shared service.
- [ ] 3.3 The GPU gate names shared services and suggests placements, and says when its consumer list is container-only. Tests cover both cases.

## 4. Storage
- [x] 4.1 A data-root resolver. Relative growing-data paths resolve under `[storage].data_root`; absolute paths keep their value; with no section, nothing changes.
- [ ] 4.2 Wire every writer of growing data through the resolver: the cycle, Nexus, Hypnos, the evaluation and research logs, backups, native Redis and Qdrant, and the models directory.
- [ ] 4.3 The wizard storage step: filesystems with free space, the recommendation, and a refusal below the minimum. On compose, it writes a gitignored local override binding the growing volumes under the root.
- [ ] 4.4 Relocation: copy, verify, then switch; never delete the original.
- [x] 4.5 A `Storage` pre-boot row against `[storage].min_free_gb`.

## 5. Docs and verification
- [ ] 5.1 Operator docs, in present tense: choosing hardware, shared services, and the data root.
- [ ] 5.2 Record a real run of the wizard on the desktop and on the Orin Nano Super. The operator runs it on the device.
