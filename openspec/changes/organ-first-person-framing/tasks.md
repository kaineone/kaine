## 1. Implementation

- [ ] 1.1 Chat client: `ChatRequest.own_turn` sends `[system, user "(next)", assistant prompt]` on both backends, drops the echoed prompt from the reply, and sets `from_content` only for generated text
- [ ] 1.2 Context assembly: situation section, lead heading, descriptive first-person personas, heard-speech guard only with heard material, `PERSONA_TEMPLATE_VERSION` "4"; the language module sends voice and probe requests with `own_turn` and the `"\n#"` stop
- [ ] 1.3 First-person disclosure default; ensuring it replaces the second-person default in place in the self-model and in the language module's own facts; `config/kaine.toml` updated
- [ ] 1.4 Docs and tests: request layout and echo stripping; prompt structure in felt and numeric renderings; no prohibitions in the default personas; guard present with each heard source and absent without; probe layout; legacy disclosure replaced in place
