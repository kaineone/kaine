## The mechanism (Tadros et al. 2022)

1. Convert the trained layer's weights to a spiking network, with thresholds scaled from the activations on recent inputs.
2. Drive it with Poisson noise whose rates match the mean input statistics, never stored inputs. That suits zero raw-sense persistence: replay needs no recorded percepts.
3. Apply local STDP-like updates, which strengthen weights between co-active units and weaken the rest.
4. Map the weights back.

## Application to KAINE

**Candidates.**
- The Chronos and Topos forward heads (single linear readouts).
- The Audition acoustic and speech-path MLPs.
- The Soma CfC readout.
- The Phantasia RSSM, which is larger and last.

**Phase.** A Hypnos phase after the existing consolidation phases, running only during sleep, with adaptation already suspended. Each learner exposes `replay_consolidate(noise_rng, budget)` through a protocol. Learners without it are skipped.

**Statistics.** Only the per-feature mean and variance that the buffer summaries already persist are used to set noise rates. No raw buffer is needed.

## Measurement before adoption

An offline interference benchmark with no entity:
1. Train a head on feed A, then on feed B.
2. Measure prediction error on A before and after B, with and without replay.

Adopt replay only if it reduces interference on A without raising error on B beyond a recorded tolerance.

## Gate

The ablation first, then the interference benchmark, then a change that ships replay off by default with a paper note.
