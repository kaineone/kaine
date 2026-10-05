# Roadmap

This page shows the engineering work in flight, the operator and on-device steps still open from finished work, and the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| attention-driven-audition | 8/16 (50%) | Move hearing beyond speech transcription so audio can drive workspace salience. |
| attention-driven-foveation | 13/18 (72%) | Replace uniform screen downsampling with a foveated capture that keeps fine detail where it matters. |
| browser-first-run | 0/22 (0%) | Replace the terminal-first setup wizard with a browser-based first-run flow, including download progress. |
| entity-key-custody | 0/12 (0%) | Redesign entity-state encryption so keys can be recovered or rotated without manual re-encryption. |
| individuation-rebuild | 56/67 (84%) | Replace the individuation signal with a real test against the being's own birth reference, produced at runtime and read the same way by preservation and decommission. The real-organ calibration (task 10) is next. |
| maturation-gate-liveness | 13/16 (81%) | Fix the developmental maturation gate so birth can complete and gestation is safely confined. |
| module-ignition-study | 29/33 (88%) | Run the same stimulus corpus with different module coalitions to measure what each faculty contributes. |
| module-residency-and-speech-tiers | 5/43 (12%) | Make the same entity run on weak hardware by selectively loading and tiering speech backends. |
| portability-program | 7/8 (88%) | Honest portability claims and verified support from small boards up to multi-GPU servers. |
| stream-wiring-quality | 11/20 (55%) | Clean up bus stream names, remove phantom reads and enforce the stream contract across modules. |

## Open operator and device steps

These steps come from changes whose code is finished and archived. Each needs the operator, a specific device, or an operator decision, so no contributor can close it alone. The archived change's `tasks.md` keeps the full wording.

| From change | Step |
| --- | --- |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: the operator confirms the research phase has ended. |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: Spot runs enabled on supervised boots, handles at least one injected module failure end to end and one escalation drill, and the operator reviews the incident logs and signs off. |
| perception-drives-salience | Boot the base-thesis form on the reference corpus and confirm perceptual discontinuities reach the workspace competition with a score that varies with the stimulus. Access-threshold calibration follows only after that passes, as its own change. |
| containerize-deployment | Measure the conscious-access-path latency in containers against host-native on GPU hardware, and confirm 10 Hz and 3.333 Hz parity. |
| claude-science-export | The operator confirms the five open design questions, which the implementation resolved with the design's recommended answers (config locus, CSV/JSON default, encrypted bundles, attestation persistence, inadmissible runs). |
| docs-base-thesis-reframe | The operator reviews the documentation before it is published. |
| headless-host-operations | On the Jetson worked-example host: run the ordered sequence and record that the remote-access gate preceded the headless switch; set and record the MAXN_SUPER power mode; enable lingering for the service user and record that units start at boot; record the NVMe swapfile and `vm.swappiness` = 10 after a reboot. |
| any-target-bootstrap | Record real install runs on the desktop, the Orin Nano Super and a Pixel 6a under Termux. |
| hardware-and-storage-selection | Record a real run of the setup wizard on the desktop and on the Orin Nano Super. |
| sherpa-onnx-speech | Install on a Pixel 6a under Termux and run the live speech round trip there. |

## Backlog totals

The roadmap contains 10 active changes, 252 archived changes and 101 capability specs.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
