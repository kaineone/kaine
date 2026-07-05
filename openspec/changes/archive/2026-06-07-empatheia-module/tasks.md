## 1. Agent model

- [x] 1.1 `kaine/modules/empatheia/agent.py` — `AgentModel` (id/label, emotion histogram, behavioral summary, reliability, interaction count, timestamps) + `familiarity()` in [0,1] from interaction count × model coverage
- [x] 1.2 Update rules: fold each observation into the histogram/summary; bump interaction count

## 2. Store (with serialize/deserialize)

- [x] 2.1 `kaine/modules/empatheia/store.py` — `AgentStore` protocol with `serialize() -> bytes` and `deserialize(data: bytes) -> None`; `QdrantAgentStore` (collection `empatheia_agents`, all-MiniLM embeddings) + `InMemoryAgentStore` for tests; both implement the serialize/deserialize contract
- [x] 2.2 `EmpatheiaMergeStrategy` (mirroring `MnemosMergeStrategy`): reconcile two diverged `AgentStore` snapshots by combining interaction counts (sum) and merging emotion histograms (weighted average by interaction count); persist the merged profiles to Qdrant before completing

## 3. Module

- [x] 3.1 `kaine/modules/empatheia/module.py` — `Empatheia(BaseModule)`. Subscribe to `audition.emotion` and `audition.transcription` (post `rename-audition-vox`) + workspace broadcast; attribute to current agent (operator-set speaker label, default `operator`); update + persist the model
- [x] 3.2 Publish `empatheia.agent_model` (id, familiarity, reliability, interaction_count) each update
- [x] 3.3 Publish `empatheia.social_error` when observed behavior deviates from the model (salience scaled by deviation; payload = agent id, salience, deviation magnitude only — no raw behavioral data)

## 4. Boot + config

- [x] 4.1 `make_empatheia` factory + `SIMPLE_FACTORIES` registration
- [x] 4.2 `[empatheia]` config (backend, collection, speaker_label default, deviation_threshold, salience) + `[modules].empatheia = false`
- [x] 4.3 Export `Empatheia` from `kaine/modules/__init__.py`

## 5. FaithfulRenderer templates

- [x] 5.1 Add `empatheia.agent_model` template to `kaine/faithful/templates.py`: renders as `"[Empatheia] {agent_label} familiarity={familiarity:.0%}"`
- [x] 5.2 Add `empatheia.social_error` template to `kaine/faithful/templates.py`: renders as `"[Empatheia] social surprise: {agent_label} deviation={deviation_magnitude:.2f} (salience {salience:.2f})"`

## 6. Tests

- [x] 6.1 `tests/test_empatheia_agent.py` — familiarity rises with interaction count; histogram/summary updates
- [x] 6.2 `tests/test_empatheia_store.py` — in-memory store roundtrip; serialize/deserialize round-trip is lossless (all fields recovered); protocol satisfied
- [x] 6.3 `tests/test_empatheia_merge.py` — fork/merge: two diverged stores merged have interaction count ≥ max of the two; histogram is a weighted average; merged profile persisted to the store
- [x] 6.4 `tests/test_empatheia_module.py` (fakeredis) — emotion events update the model; `empatheia.agent_model` published with familiarity; deviation emits `empatheia.social_error` with only id/salience/deviation in payload; social_error enters workspace with declared salience
- [x] 6.5 `tests/test_boot_wiring.py` — SIMPLE_FACTORIES includes `empatheia`

## 7. Verification

- [x] 7.1 Full unit suite green (requires `rename-audition-vox` to be merged first)
- [x] 7.2 `openspec validate empatheia-module --strict` clean
- [x] 7.3 Commit (Kaine.One), branch-per-change, merge, archive
