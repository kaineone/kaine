## 1. Package + state

- [ ] 1.1 Add `kaine.modules.lingua` to setuptools packages
- [ ] 1.2 State dir `state/lingua/` covered by existing `state/` gitignore

## 2. Chat client

- [ ] 2.1 Implement `kaine/modules/lingua/client.py` with `ChatClient` protocol, `ChatRequest`/`ChatResponse` dataclasses, `OpenAIChatClient` (httpx.AsyncClient) + `FakeChatClient`
- [ ] 2.2 Tests covering fake client behavior, request shape construction

## 3. Intent-expression log

- [ ] 3.1 Implement `kaine/modules/lingua/intent_log.py` with `IntentExpressionLog.append(...)` — atomic JSONL append carrying timestamp/mode/prompt/generated_text/model/faithful_rendering
- [ ] 3.2 Tests covering record shape, append accumulation, optional fields

## 4. Module

- [ ] 4.1 Implement `kaine/modules/lingua/module.py` with `Lingua(BaseModule)` exposing speak() / think(); two distinct publish streams; intent-expression log on each successful call
- [ ] 4.2 Update `kaine/modules/__init__.py` to export `Lingua`

## 5. Config

- [ ] 5.1 Add `[lingua]` block to `config/kaine.toml`
- [ ] 5.2 Add `lingua = false` under `[modules]`

## 6. Documentation

- [ ] 6.1 Write `kaine/modules/lingua/ABLITERATION.md` documenting the operator-approved abliteration process (not implemented in Phase 5.2)

## 7. Module tests

- [ ] 7.1 `tests/test_lingua_module.py` against fakeredis using FakeChatClient: speak → lingua.external; think → lingua.internal; cross-stream isolation; intent log captures both modes; faithful_rendering matches FaithfulRenderer output; custom client substitutes; opt-in real-chat test (`KAINE_LINGUA_RUN_REAL_CHAT=1`)

## 8. Verification

- [ ] 8.1 Full unit suite passes
- [ ] 8.2 `openspec validate lingua --strict` clean
- [ ] 8.3 Commit, merge, archive change, drop branch
