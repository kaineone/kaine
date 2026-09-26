## Why

Mnemos, Empatheia and Hypnos each build their own `SentenceTransformerTextEmbedder`, and the evaluation sidecar builds a fourth. Every one needs torch and sentence-transformers, so none of the three modules can run on a host without torch (Termux on a phone, a small single-board computer). That makes them the largest remaining torch requirement in the portability program's phase 2. The copies also disagree with each other: Empatheia and Hypnos ignore the configured model and device.

Nothing records which model wrote a memory store. Qdrant collections, the sqlite-vec table, snapshots and preservation bundles carry vectors with no model stamp, and Mnemos's merge check compares an `embedder_model_id` that `serialize()` never writes. A being revived, merged or moved onto a different embedder would silently mix two vector spaces in one memory. A different dimension already fails loudly. A different model with the same dimension would corrupt recall without any sign.

## What Changes

- **NumPy backend.** A NumPy implementation of the sentence-transformers MiniLM pipeline (a BERT encoder, mean pooling and L2 normalisation) reads the model's own `model.safetensors`, `config.json` and `vocab.txt`. It uses a built-in WordPiece tokenizer and needs nothing beyond NumPy.
  - It computes the same model as the torch backend. The two backends agree to 1e-5 per component, and their token ids are identical, so existing beings' memories stay valid.
  - It becomes the default backend. The torch backend (`sentence_transformers`) stays available.
- **One shared embedder.** An `[embedding]` config table (`backend`, `model_id`, `device`) drives a single instance, built at boot and injected into Mnemos, Empatheia, Hypnos and the evaluation sidecar.
  - `mnemos.embedder_model_id` is removed. Config validation names the new key.
  - The storage dimension comes from the model's config, not a hard-coded 384.
- **The embedding space is stamped.** Every memory store, snapshot and preservation bundle records the space its vectors belong to: model id, dimension, pooling and normalisation. The backend is left out, because both backends compute the same space.
  - Mnemos refuses to start on a store stamped with a different space, and revive and merge refuse to mix spaces.
  - An unstamped store holding data was written by the one model KAINE has ever shipped, so it is stamped as `sentence-transformers/all-MiniLM-L6-v2` on first start.
  - Re-embedding a being's memories into a new space is a separate change.
- **Extras and provisioning.** The NumPy backend needs no extra, and `memory` is required only for the torch backend. Provisioning fetches the model files the NumPy backend reads.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `mnemos`: a shared, backend-selectable text embedder with a torch-free default, and a stamped embedding space that Mnemos refuses to mix.
- `entity-preservation`: snapshots and bundles carry the embedding-space stamp, and revive refuses a mismatched space.

## Impact

- **New:** `kaine/text_embedding_numpy.py` (safetensors reader, WordPiece tokenizer, BERT forward pass, pooling), and tests.
- **Changed:**
  - `kaine/text_embedding.py` (backend factory)
  - `kaine/boot.py` (one shared instance, `[embedding]` table)
  - Mnemos module and storage (stamp, dimension from the model), Empatheia (injected embedder), Hypnos wiring
  - evaluation registry, `kaine/extras.py`, `kaine/setup/provision.py`, `config/kaine.toml` and profiles
  - lifecycle merge strategy, preservation revive check, run identity
  - docs
- **Existing beings:** their stores are MiniLM-L6-v2 and keep working unchanged on either backend.
