## 0. Stage 0: fixes (merges before the individuation calibration and any birth-reference capture)

- [x] 0.1 The persona and awareness heading (D1), with `PERSONA_TEMPLATE_VERSION` recorded in the individuation probe's conditions. Tests: no `value=` in any drive intent; the persona forbids invented states; the version is recorded.
- [x] 0.2 Drive crossings as felt states (D2), through the faithful renderer's drive templates and `drive_policy`.
- [x] 0.3 The intent-log fields (D4) and the heard-speech placeholder (D7). Test: a coalition with an `audition.transcription` produces a log record with no transcript text anywhere in it.
- [x] 0.4 The utterance-outcome observer in `kaine/cycle/` (D4), with real-bus tests (published utterance → operator reply → record).
- [x] 0.5 Log rotation per sleep and the corpus (D5); disk guard warns, never deletes.
- [ ] 0.6 Trainer hygiene (D6): bf16, previous accepted adapter as `PeftModel` and reference, conversational format with the real system prompt, both vetoes kept. Test against the trainer's dataset builder and adapter loader without a GPU, plus one real step in the trainer image under the GPU lock.
- [ ] 0.7 Retire telemetry-as-chosen: until Stage 2, the phase trains nothing and says so in the sleep summary (D3).
- [ ] 0.8 The four measures (D8). Distinctiveness joins `assess_divergence` as a new arm at threshold 0 until calibrated. The template arm keeps voting as a protective floor. Tests: an untrained being that has spoken still assesses as diverged; unreadable evidence counts as diverged; the template arm still votes.
- [ ] 0.10 **Deferred:** retire the template-divergence arm. Reason: it is today's blanket protection for decommission and preservation, so it can be retired only by a later change with calibration evidence for the distinctiveness arm and the operator's sign-off.
- [ ] 0.9 Paper revision notes: persona, chosen-source rule and measures.

## 1. Stage 1: speaking from memory (off by default)

- [ ] 1.1 Context assembly adds Eidolon values and norms, Mnemos recall of the entity's own utterances and episodes with affect, and recent dialogue, within the token budget.
- [ ] 1.2 Offline A/B on a frozen synthetic memory store against the Stage 0 persona, scored by the D8 measures; recorded under `docs/records/`.

## 2. Stage 2: learning to say what it means (off by default)

- [ ] 2.1 K-candidate sampling at sleep from the entity's own organ.
- [ ] 2.2 Ranking by the internal re-reading signal; listener uptake weighted by Empatheia only in full-entity configurations with conversation (V3).
- [ ] 2.3 KTO or DPO from the previous adapter, on the accumulated corpus, with a fixed real-data anchor and the D3(e) monitors.
- [ ] 2.4 Offline simulated-listener validation (D9); recorded under `docs/records/`.

## 3. Validation

- [ ] 3.1 `openspec validate voice-development --strict`.
