## Context

The shared class already exists: `kaine/text_embedding.py` holds `SentenceTransformerTextEmbedder` and the `Embedder` / `TextEmbedder` protocols, and all four consumers are async and return `list[float]`. What differs is how many instances there are and that each one needs torch. The model is `sentence-transformers/all-MiniLM-L6-v2`:
- a 6-layer BERT encoder: hidden size 384, 12 heads, intermediate size 1536, GELU, layer-norm eps 1e-12, 512 positions, vocabulary 30522;
- `max_seq_length` 256, a lower-casing WordPiece tokenizer, mean pooling, then Normalize.

The model is 22M parameters, which NumPy runs in milliseconds per sentence.

## Decisions

### The NumPy backend is the same model, not a lighter one
Moving to ONNX or model2vec would add a dependency, and model2vec is also a different vector space (potion-base is 256-dim). Either would force every existing being's memories through a re-embed. Running the same weights in NumPy keeps the space and adds nothing to install. A lighter model for the smallest tiers is a later, separate change that comes with re-embedding.

### `kaine/text_embedding_numpy.py`
- **Weights.** A safetensors reader: an 8-byte little-endian header length, a JSON header, then raw little-endian tensors. It supports F32 and F16 (upcast to float32), maps tensors with `numpy.frombuffer` and reshapes them. There is no `safetensors` package dependency. Tensor names are BERT's (`embeddings.word_embeddings.weight`, `encoder.layer.N.attention.self.query.weight`, …), accepted with or without a `bert.` prefix.
- **Tokenizer.** BERT basic tokenization, then WordPiece, as HuggingFace's `BertTokenizer` does it:
  - clean text: drop control characters and U+FFFD, map whitespace to a space;
  - put spaces around CJK characters;
  - lower-case and strip accents (NFD, drop Mn), because `do_lower_case` is true and `strip_accents` unset follows it;
  - split on whitespace and punctuation (ASCII punctuation ranges plus Unicode P*);
  - WordPiece: greedy longest-match-first with `##` continuations; `[UNK]` for a word longer than 100 characters or with no match;
  - add `[CLS]` … `[SEP]` and truncate to `max_seq_length` (from `sentence_bert_config.json`) including the two specials.
- **Forward pass** (float32), with mask = 1 for real tokens:
  - embeddings: word + position + token-type-0, then LayerNorm;
  - per layer: Q, K, V, split into heads, scaled dot-product with an additive mask of −inf-equivalent (a large negative) on padding, softmax, context, output dense, residual, LayerNorm; then intermediate dense, exact erf GELU, output dense, residual, LayerNorm.
  - GELU is the erf form, never the tanh approximation. It uses `scipy.special.erf` when SciPy is importable, and otherwise a vectorised NumPy erf (Abramowitz–Stegun 7.1.26 in float64: maximum absolute error 1.5e-7, well inside the 1e-5 parity bound). Element-wise `math.erf` through `numpy.vectorize` is not used, because it costs about a second per sentence.
- **Pooling.** Mean over the last hidden state weighted by the mask, then L2 normalisation (with the same 1e-12 clamp as `torch.nn.functional.normalize`). The pipeline is read from `modules.json` and `1_Pooling/config.json`. An unsupported pipeline (CLS pooling, no Normalize) raises at load rather than guessing.
- **Batching.** `encode_batch` pads to the longest sequence in the batch. Padding cannot change a result because of the mask.
- **Model location.** `[embedding].model_path` when set. Otherwise the HuggingFace cache layout for `model_id` (`$HF_HOME` or `~/.cache/huggingface`, `hub/models--<org>--<name>/refs/main` → `snapshots/<rev>/`), read without importing `huggingface_hub`. Missing files raise at `load()` with the path searched. Nothing is downloaded at runtime.

### The shared instance and config
- `[embedding]`:
  - `backend` = `"numpy"` (default) or `"sentence_transformers"`;
  - `model_id` defaults to `sentence-transformers/all-MiniLM-L6-v2`;
  - `device` = `"cpu"` by default; only the torch backend reads it;
  - `model_path` is optional.
- `make_text_embedder(config) -> Embedder` in `kaine/text_embedding.py` builds either backend. Boot builds one instance per registry and passes it to Mnemos (`embedder=`), Empatheia (a new `embedder=` argument, used by its Qdrant store), Hypnos (`consolidation_embedder`) and the evaluation sidecar. Nothing else constructs an embedder.
- **Sharing without shutting each other down.**
  - The instance handed to the modules is wrapped in `SharedEmbedder`: `load()` runs the inner load once, under an `asyncio.Lock`, and later calls return at once. `shutdown()` is a no-op, because `MnemosCore` shuts its embedder down when it stops, and a Spot restart of one module must not unload the model under the others.
  - `encode`, `encode_batch` and `embed` await `load()` first, so a consumer never has to load it. A failed load raises to that consumer, never a fake vector.
  - Every other attribute forwards to the inner embedder.
  - Empatheia loads it before it initializes its Qdrant store and sizes the store's collection from its dimension. A missing model therefore fails the module's start rather than writing zero vectors.
  - The evaluation sidecar loads its embedder when it starts. On a load failure it fails closed when `require_semantic_embedder` is set; otherwise it falls back to `HashEmbedder` with the ERROR disclosure, and records carry `hash`.
  - The registry keeps the instance as `registry.shared_embedder`. `construct_module` hands it to Mnemos, Empatheia and Hypnos through a reserved `_embedder` key in their sections, as it already does for the perception feed, so a Spot restart gets the same instance.
  - It is created on first need, so a registry with none of the three modules enabled never builds an embedder.
  - The evaluation sidecar in the cycle process takes `shared_embedder(registry, kaine_config)`, which builds the instance from `[embedding]` even when no memory module is enabled. Nexus, a separate process, builds its own through `make_text_embedder`.
- `mnemos.embedder_model_id` and `mnemos.device` are removed. `make_mnemos` rejects either with a `ConfigurationError` naming `[embedding].model_id` / `[embedding].device`.
- Mnemos sizes storage from the embedder's declared dimension. It reads `hidden_size` from the model's `config.json` before load, and `load()` checks it against the loaded model.
- Both backends set `kind` for disclosure (`"numpy_minilm"` / `"sentence_transformers"`). Run identity records `embedding_backend` and `embedding_model_id` from the resolved `[embedding]` table, defaults included.

### The embedding-space stamp
- **The stamp.**
  - It is `{"model_id": str, "dim": int, "pooling": "mean", "normalized": true}`.
  - `Embedder` gains a `space` property that returns it. `SharedEmbedder` forwards it, and `FakeEmbedder` reports its own model id and dimension.
  - The backend is not part of the space: the parity tests are what make the two backends interchangeable.
  - `LEGACY_EMBEDDING_SPACE` names `sentence-transformers/all-MiniLM-L6-v2` at 384 dimensions. It is the only model KAINE has ever shipped.
- **Storage** gains `read_stamp(key) -> dict | None` and `write_stamp(key, stamp)`, where the key is `<collection prefix>embedding_space`. The two study lines therefore keep separate stamps even where they share a store.
  - **sqlite-vec:** a `kaine_meta` table (`key TEXT PRIMARY KEY, value TEXT`) holds the stamp as JSON.
  - **Qdrant:** a collection `kaine_meta` with vector size 1. It holds one point per key, with id `uuid5(<namespace>, key)` and the stamp in its payload. It is never one of a being's memory collections, so the scoped export never touches it.
  - **In-memory:** a dictionary.
- **At `MnemosCore.initialize`**, after the collections are ensured:
  - A stamp equal to the embedder's space: proceed.
  - A stamp for a different space: raise `StorageError` naming both spaces. Mnemos does not start (fail closed), and the message says a re-embed is needed.
  - No stamp and no points in the being's own collections: write the stamp.
  - No stamp but existing points: the store predates stamping and holds `LEGACY_EMBEDDING_SPACE`. If that equals the embedder's space, write it and log that the store was stamped as legacy MiniLM. Otherwise refuse, as for a mismatch.
- **Export, bundles and merge.**
  - `MnemosCore.export_state` includes `embedding_space` (the embedder's space).
  - `import_state` compares the bundle's `embedding_space` with the running embedder's before validating or writing anything. A missing one means `LEGACY_EMBEDDING_SPACE`. A mismatch raises `StorageError`, so preservation refuses the revive. After a successful import it writes the running space as the stamp.
  - `Mnemos.serialize()` includes `embedding_space`. `MnemosMergeStrategy` compares it instead of the never-written `embedder_model_id`, and a mismatch sets its existing mismatch flag, now `embedding_space_mismatch`.
- **Empatheia's collection is not stamped.** Its vectors are never searched: only the profile payload is read back. Since `scoped-memory-preservation`, revive re-embeds every profile with the running embedder, so no vector crosses between spaces.

### Extras and provisioning
- The NumPy backend needs only NumPy (base). In `kaine/extras.py`, the `mnemos`, `empatheia` (Qdrant) and `hypnos` rows require `sentence_transformers` only when `[embedding].backend = "sentence_transformers"`.
- `kaine/setup/provision.py` fetches the model repo named by `[embedding].model_id` into the HF cache at setup time. It already does this for the old key.

## Verification
- **Tokenizer parity.** When `transformers` is importable: identical ids to `BertTokenizer` / `BertTokenizerFast` over a corpus covering ASCII, punctuation, accents, CJK, emoji, control characters, very long words and text past 256 tokens.
- **Embedding parity.** When `sentence_transformers` and the cached model are available: every sentence in the corpus within 1e-5 per component, and cosine ≥ 0.99999, of `SentenceTransformer.encode(..., normalize_embeddings=False)`. Also for batches of mixed length.
- **Without torch.** A subprocess test with torch and transformers blocked: loads and encodes on the NumPy backend from a tiny synthetic model written by the test (a 2-layer BERT, safetensors plus vocab), and checks the output against a pure-NumPy reference.
- **Stamp tests.**
  - For both storages: matching stamp; mismatched stamp refuses; legacy store stamped; empty store stamped.
  - Revive with a mismatched space refuses; the merge check fires.
- **Mutants.** GELU approximation, pooling without the mask, missing normalisation, and a tokenizer without accent stripping are all caught.

## Risks
- **Speed.** A NumPy BERT is slower than torch on a GPU host, but the embedder was already pinned to the CPU there. The Soma and Chronos CfC precedent (1e-5 parity, the NumPy default) applies.
- **Store collisions.** A different model with the same dimension (another 384-dim model) would have collided silently before this change. The stamp now makes that refuse. This is the intended safety behaviour, and the operator sees a named error.
