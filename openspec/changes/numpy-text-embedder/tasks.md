## 1. NumPy backend

- [ ] 1.1 `kaine/text_embedding_numpy.py`: safetensors reader, WordPiece tokenizer, BERT forward pass, mean pooling and normalisation, model location without `huggingface_hub`.
- [ ] 1.2 Parity tests (tokenizer and embeddings) against transformers / sentence-transformers where available; a torch-blocked subprocess test on a synthetic model; mutants caught.

## 2. One shared embedder

- [ ] 2.1 `[embedding]` table and `make_text_embedder`; one instance per registry injected into Mnemos, Empatheia, Hypnos and the evaluation sidecar; `mnemos.embedder_model_id` rejected with a pointer to the new key.
- [ ] 2.2 Storage dimension from the model's configuration; run identity from the instance.
- [ ] 2.3 `kaine/extras.py` rows, `kaine/setup/provision.py`, `config/kaine.toml` and profiles.

## 3. Embedding-space stamp

- [ ] 3.1 `Embedder.space`; sqlite-vec `kaine_meta` and Qdrant `<prefix>kaine_meta` stamps; start-up check (match, refuse, legacy, empty); Empatheia's collection likewise.
- [ ] 3.2 Stamp in `serialize()`, export and bundles; revive and merge refuse a mismatch; unstamped bundles treated as legacy MiniLM.

## 4. Docs and verification

- [ ] 4.1 Mnemos, Empatheia, Hypnos, configuration, deployment-tiers, hardware and getting-started docs.
- [ ] 4.2 Offline suite green; `openspec validate numpy-text-embedder --strict`.
