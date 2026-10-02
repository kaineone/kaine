# Roadmap

This page shows the engineering work currently in flight, along with the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| any-target-bootstrap | 6/7 (86%) | One install entry point that works on a desktop, a Jetson Orin Nano Super and Termux on a Pixel 6a. |
| attention-driven-audition | 8/16 (50%) | Move hearing beyond speech transcription so audio can drive workspace salience. |
| attention-driven-foveation | 13/18 (72%) | Replace uniform screen downsampling with a foveated capture that keeps fine detail where it matters. |
| browser-first-run | 0/22 (0%) | Replace the terminal-first setup wizard with a browser-based first-run flow, including download progress. |
| bus-cancellation-safety | 10/11 (91%) | Make every long-running loop actually stop when its `asyncio.CancelledError` reaches it. |
| claude-science-export | 25/26 (96%) | Build an exploratory-analysis workbench for the companion paper's seven experiments. |
| containerize-deployment | 18/19 (95%) | Containerise the full reference deployment as a precondition for public release. |
| docs-base-thesis-reframe | 13/15 (87%) | Align the documentation with the base-thesis default of five predictive workspace processors. |
| entity-key-custody | 0/12 (0%) | Redesign entity-state encryption so keys can be recovered or rotated without manual re-encryption. |
| hardware-and-storage-selection | 16/17 (94%) | Let the operator choose which GPU, how much GPU memory and which storage path KAINE uses. |
| headless-host-operations | 47/51 (92%) | Document and harden running KAINE as a dedicated, 24/7 headless host. |
| maturation-gate-liveness | 13/16 (81%) | Fix the developmental maturation gate so birth can complete and gestation is safely confined. |
| module-ignition-study | 29/33 (88%) | Run the same stimulus corpus with different module coalitions to measure what each faculty contributes. |
| module-residency-and-speech-tiers | 5/43 (12%) | Make the same entity run on weak hardware by selectively loading and tiering speech backends. |
| nexus-privacy-hardening | 31/33 (94%) | Add authentication, CSRF and Origin checks to Nexus and stop leaking raw cognitive content by default. |
| organ-sleeps-when-idle | 5/7 (71%) | Unload the organ model server when no cycle is using it. |
| perception-drives-salience | 9/11 (82%) | Wire perception-derived prediction error into the workspace so it can win conscious access. |
| portability-program | 7/8 (88%) | Honest portability claims and verified support from small boards up to multi-GPU servers. |
| sherpa-onnx-speech | 10/11 (91%) | Torch-free speech recognition and synthesis for edge and Termux targets. |
| stream-wiring-quality | 11/20 (55%) | Clean up bus stream names, remove phantom reads and enforce the stream contract across modules. |
| unattended-boot-via-safety-net | 45/47 (96%) | Allow an entity to start without an operator present once the safety net and Spot supervisor are trusted. |

## Backlog totals

The roadmap currently contains 21 active changes, 200 archived changes and 90 capability specs.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
