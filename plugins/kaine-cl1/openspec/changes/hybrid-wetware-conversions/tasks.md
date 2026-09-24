## 1. Audition front end (default-off)

- [ ] 1.1 `WetwareAcousticFrontEnd` behind Audition's front-end salience seam;
      STT/emotion untouched — `kaine_cl1/backends/audition_frontend.py`.
- [ ] 1.2 Encode audio envelope → temporal stim; decode surprise → salience.
- [ ] 1.3 Gate: salience rises for novel/changing sound vs habituated sound.

## 2. Phantasia surprise read-out (default-off)

- [ ] 2.1 `WetwareSurprise` sourcing the RSSM surprise scalar from criticality/LZ;
      rollout stays silicon — `kaine_cl1/backends/phantasia_surprise.py`.
- [ ] 2.2 Gate: surprise correlates with the silicon RSSM surprise on held-out
      sequences above a stated threshold.

## 3. Volition / action-selection (default-off)

- [ ] 3.1 `WetwareActionSelector` closed loop: encode state → stim, decode action
      → intent — `kaine_cl1/backends/volition.py`.
- [ ] 3.2 Gate: on a toy 2-choice task in the simulator, decoded action beats
      chance across seeds; otherwise stays disabled.
- [ ] 3.3 Any decoded action still passes through KAINE's unchanged two-layer
      safety gate before it can become an outward act.

## 4. Thymos affect read-out (default-off, review-gated)

- [ ] 4.1 `WetwareAffect` reading valence/arousal from population dynamics —
      `kaine_cl1/backends/thymos.py`.
- [ ] 4.2 Gate: requires explicit `[backends.hybrid].thymos_reviewed = true`
      even in the simulator; never drives outward action.
- [ ] 4.3 Gate: arousal read-out tracks injected global-excitability changes.

## 5. Cross-cutting

- [ ] 5.1 All four keep upstream `<name>.out` schemas (schema-equality tests).
- [ ] 5.2 Broker refuses to bring online more converted modules than the 64
      channels allow; the drop is logged, never silent.
- [ ] 5.3 `openspec validate hybrid-wetware-conversions --strict` passes.
