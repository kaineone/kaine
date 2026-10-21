## 1. Implementation

- [ ] 1.1 Remove the name line from the persona, and remove `_name_from` and its comment
- [ ] 1.2 Retire `[language].persona_name` with a boot warning, keep the persona digest's shape, and set `PERSONA_TEMPLATE_VERSION` to "7"
- [ ] 1.3 Tests: a self-model document with a name and a set `persona_name` each leave the system text and the prompt without the name, the retired key warns and is ignored, and the default digest is unchanged
- [ ] 1.4 Update docs/09-modules/language.md and docs/appendix-a-configuration/modules.md
