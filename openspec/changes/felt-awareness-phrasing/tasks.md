## 1. Implementation

- [ ] 1.1 Felt template set with documented bin constants, a number-free fallback and digit guard, and a heard-speech redactor for it (`kaine/faithful/felt.py`), with tests for every bin edge
- [ ] 1.2 Report and planning `about` as a felt phrase with `about_kind` `"felt"` and `about_values` on the intent, selected by `[language].awareness_rendering`, with tests
- [ ] 1.3 Context assembler and language module render the felt block, log `numeric_rendering` and `about_values`, reworded persona and guard, `PERSONA_TEMPLATE_VERSION` 3, config key in the factory, with tests (no digits, logs keep values, numeric bit for bit, guard text)
- [ ] 1.4 Config defaults (`config/kaine.toml`, first_configuration profile) and `docs/09-modules/language.md`
