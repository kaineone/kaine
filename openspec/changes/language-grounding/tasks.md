## 0. Decisions and gates

- [ ] 0.1 Operator ruling: may learned-name word strings persist (a lexicon derived from heard speech, with no utterances), or only salted hashes (D4)?
- [ ] 0.2 Gate: the module-addition study has finished. No task in sections 1 to 5 changes an image a running study uses.
- [ ] 0.3 Verify the cited sources against their texts (Quinn, Eimas and Rosenkrantz 1993; Smith and Yu 2008; Kulis and Jordan 2012; Carpenter and Grossberg 1987) and put the verified citation at each code site.

## 1. Stage 1: prototypes

- [ ] 1.1 `kaine/modules/prototypes.py`: online store, acceptance radius from the distance quantile, decay, pruning, merging. Tests: `tests/test_perceptual_prototypes.py` (repeat matches, no configured categories, prune and merge).
- [ ] 1.2 Vision integration and report fields; audition when its encoder provides a latent. Tests: extend `tests/test_vision_module.py` and the audition module tests; the scorer's score is unchanged with prototypes on.
- [ ] 1.3 Persistence, encryption, bundles, fork copy and merge; privacy-filter vector fields. Tests: `tests/test_prototype_persistence.py`, extend `tests/test_privacy_strip_vectors.py` and `tests/test_zero_persistence_invariant.py`.
- [ ] 1.4 Offline check on the study films with no entity: assignment stability across two viewings against a shuffled control, prototype count over time. Record under `docs/records/validation/perceptual-prototypes/`.

## 2. Stage 2: referential rendering

- [ ] 2.1 Relational phrases in `kaine/faithful/felt.py`, each emitted only when its state holds. Tests: `tests/test_felt_prototype_rendering.py` (returning scene, prototypes off unchanged, no name without a learned name).
- [ ] 2.2 Organ replay of recorded coalitions rendered both ways (`organ-replay-harness`): identity leakage, degeneration and grounding measures from `voice-development`. Record the result.
- [ ] 2.3 A new individuation reference procedure note for entities that gain prototypes.

## 3. Stage 3: word learning (after 0.1, with speech-to-text on)

- [ ] 3.1 The cross-situational learner and its store. Tests: `tests/test_word_referent_learner.py` (strength and specificity rule, decay, function words by spread).
- [ ] 3.2 Store contents: weights and lexicon or hashes only. Tests: no utterance sequence in the store; hashed mode.
- [ ] 3.3 Offline benchmark on scripted narrated clips (no entity), with a shuffled-pairing control. Record it.

## 4. Cross-modal links (with stage 2)

- [ ] 4.1 Decaying co-occurrence counts between visual and auditory prototypes; a link when the pointwise-mutual-information margin is exceeded; links persisted and private like prototypes. Tests: `tests/test_prototype_links.py` (co-occurring pair links; independent pair does not; a learned name crosses a link only with the qualifier).

## 5. Validation and docs

- [ ] 5.1 One supervised validation boot after stages 1 and 2, with the pre-boot dry run shown green first.
- [ ] 5.2 Docs: `docs/09-modules/vision.md`, `audition.md`, `language.md`; paper revision note for §3.5 and §9 ("reference to the entity's own perceptual categories", not understanding).
- [ ] 5.3 `openspec validate language-grounding --strict`.
