## 1. Compose + bootstrap

- [ ] 1.1 Add `compose/qdrant.yml` (Qdrant on 127.0.0.1:6533, mandatory API key, named volume, healthcheck)
- [ ] 1.2 Append `KAINE_QDRANT_API_KEY=` (commented) to `compose/.env.example`
- [ ] 1.3 Write `scripts/qdrant-bootstrap.sh` mirroring `scripts/redis-bootstrap.sh`
- [ ] 1.4 Update `config/secrets.example.toml` adding `[qdrant]` block

## 2. Dependencies and packaging

- [ ] 2.1 Add `qdrant-client>=1.7,<2` and `sentence-transformers>=2.7,<6` to `[project.dependencies]`
- [ ] 2.2 Add `kaine.modules.mnemos` to the setuptools packages list
- [ ] 2.3 `pip install -e .[test]` in the venv

## 3. Embeddings

- [ ] 3.1 Implement `kaine/modules/mnemos/embeddings.py` with `Embedder` protocol, `SentenceTransformerEmbedder` (lazy load, device via select_device, telemetry disabled), and `FakeEmbedder` for tests
- [ ] 3.2 Tests in `tests/test_mnemos_embeddings.py`: FakeEmbedder protocol satisfaction, deterministic output, dimension match, batch path

## 4. Storage

- [ ] 4.1 Implement `kaine/modules/mnemos/storage.py` with `MemoryStorage` protocol, `RecalledMemory` dataclass, `QdrantStorage` (mandatory api_key), and `InMemoryStorage` fallback
- [ ] 4.2 Tests in `tests/test_mnemos_storage.py` against `InMemoryStorage`: collection creation, store, recall top-k by cosine, missing collection error

## 5. Memory core

- [ ] 5.1 Implement `kaine/modules/mnemos/memory.py` with `MnemosCore` orchestrating embedder + storage, short-term deque, consolidation logic, emotional retrigger hook
- [ ] 5.2 Tests in `tests/test_mnemos_memory.py`: store→recall roundtrip, capacity eviction, hook firing, recall summary excludes contents

## 6. Module

- [ ] 6.1 Implement `kaine/modules/mnemos/module.py` with `Mnemos(BaseModule)` orchestrating `MnemosCore`; on_workspace stores each broadcast in short-term and publishes `mnemos.recall` only on explicit recall API calls (not on store)
- [ ] 6.2 Update `kaine/modules/__init__.py` to export `Mnemos`

## 7. Config

- [ ] 7.1 Add `[mnemos]` block to `config/kaine.toml`
- [ ] 7.2 Add `mnemos = false` under `[modules]`

## 8. Module tests

- [ ] 8.1 `tests/test_mnemos_module.py` covering: workspace broadcast → short-term entry; recall → `mnemos.recall` event with diagnostics-only payload; capacity-driven consolidation through real module path; ser/de

## 9. Verification

- [ ] 9.1 Full unit suite passes
- [ ] 9.2 `openspec validate mnemos --strict` clean
- [ ] 9.3 Update `DEPENDENCIES.md` with qdrant-client, sentence-transformers, and Qdrant container rows
- [ ] 9.4 Commit, merge, archive change, drop branch
