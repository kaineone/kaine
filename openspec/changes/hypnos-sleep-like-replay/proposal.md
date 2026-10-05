## Why

KAINE's small learned parts adapt online while the entity is awake: the Soma readout, the Topos, Audition and Chronos forward heads, and the Phantasia RSSM. Each suspends adaptation during sleep, but nothing protects what it learned earlier from interference by what it learns later.

The paper already cites the mechanism that would: sleep-like replay in Wei, Krishnan and Bazhenov 2016 (J Neurosci 36:4231–4247). Tadros, Krishnan, Ramyaa and Bazhenov (Nat Commun 13:7742, 2022) showed that running a trained network as a spiking network driven by noise, with local Hebbian updates, recovers the structure of earlier tasks (alternatives review 2026-10-05, §5.5).

**Design document only.** Nothing is built until the workspace-mediation ablation has run. Changing how the learned heads consolidate changes what they predict, and so what competes in the workspace.

## What Changes

A design for a noise-driven, local-Hebbian replay phase in Hypnos:
- It applies to the small online learners, one learner at a time.
- It runs inside the existing sleep window.
- It is gated by a measured interference test.

## Impact

- Code: none in this change.
- Licence: the reference code (`tmtadros/SleepReplayConsolidation`) is MATLAB with no licence, so the method is reimplemented from the paper. Nothing is vendored.
