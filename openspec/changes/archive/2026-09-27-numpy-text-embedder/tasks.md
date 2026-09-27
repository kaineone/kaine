## 1. NumPy backend

- [x] 1.1 `kaine/text_embedding_numpy.py`: safetensors reader, WordPiece tokenizer, BERT forward pass, mean pooling and normalisation, model location without `huggingface_hub`.
- [x] 1.2 Parity tests (tokenizer and embeddings) against transformers / sentence-transformers where available; a torch-blocked subprocess test on a synthetic model; mutants caught.

## 2. One shared embedder

- [x] 2.1 `[embedding]` table and `make_text_embedder`; one instance per registry injected into Mnemos, Empatheia, Hypnos and the evaluation sidecar; `mnemos.embedder_model_id` rejected with a pointer to the new key.
- [x] 2.2 Storage dimension from the model's configuration; run identity from the instance.
- [x] 2.3 `kaine/extras.py` rows, `kaine/setup/provision.py`, `config/kaine.toml` and profiles.

## 3. Embedding-space stamp

- [x] 3.1 `Embedder.space`; stamps in sqlite-vec `kaine_meta`, a Qdrant `kaine_meta` collection and in memory, keyed by collection prefix; start-up check (match, refuse, legacy, empty).
- [x] 3.2 Stamp in `serialize()`, export and bundles; revive refuses a mismatch and merge flags it; unstamped bundles treated as legacy MiniLM.

## 4. Docs and verification

- [x] 4.1 Mnemos, Empatheia, Hypnos, configuration, deployment-tiers, hardware and getting-started docs.
- [x] 4.2 Offline suite green; `openspec validate numpy-text-embedder --strict`.
