## 1. Context plumbing

- [x] 1.1 `kaine/modules/context.py`: `featurize_events`, per-event additive contributions, `BroadcastContext` (adopt accessed members, ignore inhibited, vector with age, null vector from running per-source sums).
- [x] 1.2 Syneidesis writes `metadata["access_threshold"]`.
- [x] 1.3 Tests: the featurization matches Chronos's featurizer on the shared components; inhibited broadcasts are not adopted; riders below the threshold are excluded; the null vector keeps kept sources' share and replaces the rest by its running mean.

## 2. Topos and Audition

- [x] 2.1 Forward models take the context; checkpoints without context weights restore with zeros.
- [x] 2.2 Modules adopt the context from the broadcast stream and publish the per-report information gain.

## 3. Soma

- [ ] 3.1 Readout takes the context; Lingua's share is kept in Soma's null context.

## 4. Docs

- [ ] 4.1 Module pages and the cognitive-cycle chapter describe the context.
