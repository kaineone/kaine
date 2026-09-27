## ADDED Requirements

### Requirement: One shared text embedder with a torch-free default
KAINE SHALL build a single text embedder per registry from the `[embedding]` configuration and SHALL give that one instance to Mnemos, Empatheia, Hypnos and the evaluation sidecar. The default backend SHALL be a NumPy implementation of the configured sentence-transformers model that needs no torch, sentence-transformers or transformers, and that matches the sentence-transformers backend to 1e-5 per component with identical token ids. The storage dimension SHALL come from the model's configuration.

#### Scenario: A host without torch
- **WHEN** KAINE starts Mnemos with the default embedding backend where torch cannot be imported
- **THEN** Mnemos loads the model from its files on disk, encodes text, and the extras check does not require the `memory` extra for it

#### Scenario: The same vectors on either backend
- **WHEN** the same text is embedded by the NumPy and the sentence-transformers backends from the same model
- **THEN** the vectors agree to 1e-5 in every component

### Requirement: A memory store is bound to its embedding space
Every Mnemos store SHALL carry a stamp naming the embedding space its vectors belong to (model id, dimension, pooling and normalisation). Mnemos SHALL refuse to start on a store stamped with a different space than its embedder's, and SHALL never write vectors from two spaces into one store. A store with points but no stamp SHALL be treated as `sentence-transformers/all-MiniLM-L6-v2` when its dimension matches, stamped as such, and logged; otherwise Mnemos SHALL refuse it.

#### Scenario: A different model on an existing store
- **WHEN** Mnemos starts with an embedder whose space differs from the store's stamp
- **THEN** it fails to start with an error naming both spaces, and the store is unchanged

#### Scenario: A store from before stamping
- **WHEN** Mnemos starts on a 384-dimension store with points and no stamp, using MiniLM-L6-v2
- **THEN** it stamps the store as MiniLM-L6-v2, logs that it did, and starts

## MODIFIED Requirements

### Requirement: Default Mnemos config and disabled-by-default
The repository SHALL ship a `[mnemos]` block in `config/kaine.toml`
with default values for `backend` (`qdrant`), `collection_prefix`,
`short_term_capacity`, `recall_top_k`, `baseline_salience` and
`alert_salience`, and an `[embedding]` block with `backend` (`numpy`),
`model_id` and `device`. `[mnemos]` SHALL NOT accept `embedder_model_id`
or `device`: boot SHALL reject either with an error naming the
`[embedding]` key that replaces it. The `[modules].mnemos = false` flag
SHALL keep first boot from auto-registering Mnemos.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[mnemos]` section with the documented keys, an `[embedding]` section, and `[modules].mnemos == false`

#### Scenario: The old embedder keys are refused
- **WHEN** an operator config sets `[mnemos].embedder_model_id` or `[mnemos].device`
- **THEN** boot fails with an error naming `[embedding].model_id` or `[embedding].device`
