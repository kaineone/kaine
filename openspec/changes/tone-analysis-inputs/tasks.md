## 1. Tone variant

- [x] 1.1 Audition: nu~utt_t per A.2, `tone_rule` categorical or error_ratio, `tone_error_ratio`, `tone_rule` and `classified` on `audition.emotion`
- [x] 1.2 Factory key, shipped default, studies may set `[audition].tone_rule` only
- [x] 1.3 Studies `workspace_mediation_pilot_tone` and `workspace_mediation_tone`; roles; the gate checks each study's tone rule
- [x] 1.4 Tests

## 2. Records and analysis

- [x] 2.1 Research log: entry ids of tone events and broadcast members, tone fields; range sweep
- [x] 2.2 Exact sign test and decision-rule verdict in `calibration_rules.py`
- [x] 2.3 `kaine/experiment/tone_analysis.py`: tone events, accessed fractions, difference, adjusted difference over the bins, verdicts, runs still needed
- [x] 2.4 Tests on synthetic runs with a known difference

## 3. Calibration

- [x] 3.1 Plan and record accept a tone-variant run per pilot; checks of study, seed, film program and tone rule
- [x] 3.2 Tone bins and the minimum effects of both tone tests (paper PR #30); arm pilots with the variant's rule refused
- [x] 3.3 Loader requires the tone runs and settings in a complete record
- [x] 3.4 Tests

## 4. Docs

- [x] 4.1 Audition, research event streams, experiments, configuration reference
