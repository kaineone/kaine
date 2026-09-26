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
- `mnemos.embedder_model_id` is removed; configuration validation rejects it and names `[embedding].model_id`.
- Mnemos sizes storage from the embedder's declared dimension. It reads `hidden_size` from the model's `config.json` before load, and `load()` checks it against the loaded model.
- Both backends set `kind` for disclosure (`"numpy_minilm"` / `"sentence_transformers"`). Run identity records the backend and `model_id` from the instance, not from a config string.

### The embedding-space stamp
- The stamp is `{"model_id": str, "dim": int, "pooling": "mean", "normalized": true}`. `Embedder` gains a `space` property that returns it. The backend is not part of the space: the parity tests are what make the two backends interchangeable.
- **sqlite-vec:** a `kaine_meta` table (`key TEXT PRIMARY KEY, value TEXT`) holds the stamp as JSON under `embedding_space`.
- **Qdrant:** a collection `<prefix>kaine_meta` with a single point, id 1, vector size 1, and the stamp in its payload. `<prefix>` is the collection prefix Mnemos already uses, so the two study lines stay separate. Storage `export` skips the meta collection, and the stamp travels in the exported state instead.
- **At `initialize`:**
  - a stamp equal to the embedder's space → proceed;
  - a stamp for a different space → `StorageError` naming both spaces. Mnemos does not start (fail closed), and the log says a re-embed is needed.
  - no stamp and no points → write the stamp;
  - no stamp but existing points → the store predates stamping. Only MiniLM-L6-v2 has ever shipped, so if its dimension matches, write that model's stamp and log that the store was stamped as legacy MiniLM. Otherwise refuse.
- **Serialize, export and bundles:**
  - `Mnemos.serialize()` and `export_preservation_state` include `embedding_space`.
  - `import_` and revive compare it with the running embedder's space and raise on a mismatch, so preservation refuses the revive. A missing stamp in a bundle is treated as legacy MiniLM, as above.
  - `MnemosMergeStrategy` compares `embedding_space` instead of the never-written `embedder_model_id`.
- **Empatheia's collection** is written only through the same shared embedder, and is stamped and checked the same way under its own meta key.

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
