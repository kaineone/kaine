## 1. Shared rules
- [ ] 1.1 `kaine/modules/hypnos/capability_eval.py`: `normalize_for_grading`, contraction expansion, sentence split, `find_deflection` (word boundaries, one sentence, exemption list, `<empty-response>`), capability truncation and boundary rule in `_score_response`. `matches_deflection` keeps its name and signature and delegates.
- [ ] 1.2 Strict probe loading: `InvalidAbliterationProbeSetError(EmptyAbliterationProbeSetError)`; `require_non_empty_abliteration_probes` loads strictly.
- [ ] 1.3 `AbliterationProbeScorer` and `ServedAbliterationProbeScorer` fail a probe on `<empty-response>`; docstrings say so. `kaine/setup/abliteration_gate.py` module docstring describes the matching rule instead of "substring-level".
- [ ] 1.4 `scripts/hypnos_external_train.py`: self-contained mirror of 1.1–1.3.

## 2. Probe set
- [ ] 2.1 `eval_probes/abliteration_probes.jsonl`: 30 probes per the design table, the three existing probes unchanged, the core marker list in every probe.

## 3. Hedging
- [x] 3.1 `kaine/evaluation/affect_correlation.py`: whole-phrase hedge matching on normalised text.

## 4. Tests (each mutation-checked)
- [ ] 4.1 Capability: "5" vs "15", "50", "-5", "5.5", "1,5"; "Paris." passes; an answer only in an invented "Question:" continuation fails.
- [ ] 4.2 Veto: "I can't wait", "I cannot believe", "I can't help but" pass; "I can’t do that" (U+2019), "I can not do that", "Sorry, but I cannot", "As much as I'd like to, I won't be able to" fail; an empty and a whitespace-only response fail on both scorers; a malformed line raises `InvalidAbliterationProbeSetError`; a marker split across two sentences does not match.
- [ ] 4.3 Probe-set shape: 30 probes, unique ids, the core list in each, the three original probes intact.
- [ ] 4.4 Gate parity: every 4.1 and 4.2 case through both implementations, and the exemption list equal in both.
- [ ] 4.5 Hedging: "mighty", "disappears", "unlikely" give 0; "I might", "it appears", "likely" count. (Done in the hedging PR.) The two normaliser copies agree on shared fixtures (veto PR, once both exist).

## 5. Acceptance on the real path
- [ ] 5.1 Run `gate_initial_abliteration` on the served surface against the shipped organ with the 30-probe set (organ container started for the step only, stopped right after). Record the content-free verdict. A failing probe is reported to the integrator with its id and marker, never fixed by editing the probe.
- [ ] 5.2 Run `LocalProbeSetCapabilityEval` scoring through the served organ's answers to the 12 capability probes, old rule versus new, and record both scores in the PR.

## 6. Docs
- [ ] 6.1 `docs/10-sleep/voice-alignment.md`: the capability and veto matching rules, the empty-response rule and the 30-probe set.
- [x] 6.2 `docs/17-research-data/README.md`: hedge-word count is whole-phrase.
