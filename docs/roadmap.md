# Roadmap

> **This file is generated - do not edit by hand.**
> Regenerate with `~/.claude/bin/openspec-roadmap.sh` from the project root.
> Generated on 2026-09-15 (UTC).
> **Note:** The generator script is missing on this host, so this file is maintained by hand. Last corrected 2026-09-22 to match each change's tasks.md after review.

## In flight

| Change | Progress | Capabilities | Deltas | Summary |
| --- | --- | --- | --- | --- |
| claude-science-export | 25/26 (96%) | claude-science-export | ADDED | The companion empirical paper needs an exploratory-analysis and write... |
| containerize-deployment | 18/19 (94%) | containerized-deployment | ADDED | The paper names this as planned future work and as a precondition for... |
| docs-base-thesis-reframe | 13/15 (86%) | documentation-consistency | ADDED | The project has been reconfigured to its **base-thesis form** as the ... |
| perception-drives-salience | 9/11 (81%) | topos-perception | MODIFIED | The base thesis is that perception enters the workspace **as predicti... |
| attention-driven-foveation | 13/18 (72%) | topos, topos-foveation | ADDED | Screen perception currently scales the whole screen to Topos's fixed ... |
| headless-host-operations | 47/51 (92%) | headless-host-operations | ADDED | KAINE's docs cover installing the software and bringing up services. ... |
| nexus-privacy-hardening | 20/23 (87%) | evaluation-sidecar, nexus-auth, nexus-csrf-protection, nexus-dashboard, nexus-observability, remote-bridge, state-encryption | ADDED, MODIFIED | Nexus auth, CSRF and trajectory filtering landed; the dashboard and SSE stream cannot yet send the token, the containerised Nexus refuses its bind, and the token is not read from `secrets.toml`... |
| stream-wiring-quality | 11/20 (55%) | architecture-boundaries, evaluation-observers, event-bus, lingua, stream-contract | ADDED, MODIFIED | `lingua.out` aggregate, observer consolidation and ruff enforcement landed; canonical stream names in observers and the per-stream maxlen key check remain... |
| attention-driven-audition | 8/16 (50%) | audition, audition-predictive, auditory-perception | ADDED, MODIFIED | Hearing is currently **speech transcription for the language organ**,... |
| module-residency-and-speech-tiers | 0/43 (0%) | module-residency, speech-backend-tiers | ADDED | KAINE is meant to be hyper-portable and hyper-scalable. Today, when t... |
| unattended-boot-via-safety-net | 0/46 (0%) | spot-supervisor, unattended-boot | ADDED | Build deferred until research ends and Spot has a reviewed track record; eight-condition gate incl. caretaker notice and continuous input |

## Recently landed

| Date | Change |
| --- | --- |
| 2026-09-25 | cl1-substrate-plugin |
| 2026-09-25 | adaptive-access-rate |
| 2026-09-25 | fix-lingua-realization-audit |
| 2026-09-25 | torch-stack-coherence |
| 2026-09-25 | paracosmic-connector (retired unbuilt; superseded by body-agnostic-embodiment-adapters) |
| 2026-09-19 | developmental-maturation-gate (6 tasks reopened after review; see its tasks.md) |
| 2026-09-17 | portability-tiers |
| 2026-09-17 | condition-language-organ |
| 2026-09-17 | performance-test-coverage |
| 2026-09-17 | deployment-consistency |
| 2026-09-15 | host-aware-accelerator-provisioning |
| 2026-09-09 | coldstart-welfare-spot-honor-warmup |
| 2026-09-09 | fix-preboot-probe-parity |
| 2026-09-09 | fix-research-event-contracts |
| 2026-09-09 | playlist-sleep-pause |
| 2026-09-09 | pre-boot-correctness-batch |
| 2026-09-09 | research-run-infra-hardening |
| 2026-09-09 | sleep-ignition-audit |
| 2026-09-08 | authenticate-intent-provenance |
| 2026-09-08 | default-real-adapter-merge |
| 2026-09-08 | distributed-substrate |
| 2026-09-08 | evaluation-suite-rigor |
| 2026-09-08 | harden-security-boundaries |
| 2026-09-08 | interruptible-utterance |
| 2026-09-08 | nexus-realtime-polish |

_Showing the 15 most recent of 150 archived changes._

## Capabilities

| Capability | Requirements |
| --- | --- |
| abliterated-organ | 4 |
| action-selection | 4 |
| active-inference-benchmark | 5 |
| adapter-ties-dare-merge | 10 |
| architecture-boundaries | 2 |
| audio-input | 7 |
| audio-output | 8 |
| audition | 4 |
| audition-predictive | 3 |
| audition-prosody | 1 |
| batch-offload | 5 |
| chronos | 8 |
| chronos-predictive | 1 |
| cognitive-cycle | 14 |
| distributed-deployment | 6 |
| divergence-assessment | 3 |
| dynamic-hardware | 6 |
| eidolon | 8 |
| eidolon-self-inference | 5 |
| empatheia | 7 |
| enforcement-red-team | 7 |
| entity-decommission | 7 |
| entity-preservation | 15 |
| entity-time | 5 |
| evaluation-observers | 12 |
| evaluation-sidecar | 14 |
| event-bus | 10 |
| experiment-foundation | 8 |
| faithful-renderer | 6 |
| first-run-wizard | 6 |
| gpu-preflight | 2 |
| hypnos | 8 |
| hypnos-consolidation | 4 |
| hypnos-fatigue-phases | 4 |
| individuation-boundary | 4 |
| inference-backend | 4 |
| interruptible-utterance | 4 |
| license-compliance | 3 |
| lingua | 11 |
| log-validation | 1 |
| minimal-run-configuration | 4 |
| mnemos | 11 |
| mnemos-replay | 4 |
| module-pattern | 7 |
| nexus-auth | 3 |
| nexus-csrf-protection | 3 |
| nexus-dashboard | 7 |
| nexus-observability | 21 |
| nous-active-inference | 7 |
| organ-provisioning | 7 |
| oscillatory-binding | 8 |
| performance-hot-path | 6 |
| perception-feed | 1 |
| perception-locus | 3 |
| phantasia | 8 |
| praxis | 10 |
| quadlet-volumes | 1 |
| redis-bootstrap | 2 |
| remote-bridge | 4 |
| reproducible-perception | 7 |
| research-event-log | 4 |
| research-submission | 4 |
| run-admissibility | 1 |
| self-initiated-report | 4 |
| soma | 7 |
| soma-predictive | 5 |
| spot-supervisor | 15 |
| state-encryption | 5 |
| stream-contract | 2 |
| syneidesis | 8 |
| thesis-test-configuration | 3 |
| thymos | 11 |
| thymos-affect-coupling | 3 |
| topos | 12 |
| topos-predictive | 3 |
| voice-alignment | 3 |
| voice-alignment-training | 13 |
| vox | 2 |
| vox-prosodic-mirroring | 2 |
| welfare-monitoring | 4 |
| workspace-mediation-ablation | 7 |

_Total: 81 capabilities, 488 requirements._

---

17 changes in flight, 150 archived, 81 capabilities.
