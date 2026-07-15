# Empatheia

**Gated** — built and tested, shipped disabled; held behind a positive base-thesis result (see [Architecture](../architecture.md)).

KAINE's social-cognition organ: per-agent theory-of-mind models, familiarity tracking, and social prediction-error salience.

---

## Status

Implemented. Ships **disabled** — `[modules].empatheia = false` in `config/kaine.toml`.

- Consumes the `audition.emotion` and `audition.transcription` event types published by Audition.
- Production backend: Qdrant (shared Qdrant instance with Mnemos; collection `empatheia_agents`).
- Test/minimal backend: `InMemoryAgentStore` (no external services; `backend = "inmemory"`).
- Speaker diarization (v1 limitation): a single operator-set label (`speaker_label = "operator"`) is used. Multi-speaker diarization is future work (paper §10).

---

## Responsibility

In the PP+GWT framing, Empatheia is KAINE's social cognition module. It maintains probabilistic models of agents it interacts with and signals when an agent's behavior deviates from its established pattern.

Two core outputs:
1. **`empatheia.agent_model`** — numeric metadata about a known agent (familiarity, reliability, interaction count). Published on every update. The familiarity score feeds directly into Thymos affect coupling (when `[thymos.coupling].enabled = true`).
2. **`empatheia.social_error`** — a salience-only signal published when an agent's observed emotion deviates beyond `deviation_threshold`. It enters the Syneidesis workspace and raises attention by salience alone; it does not carry raw behavioral data or transcript text to any surface.

Zero raw-sense-data commitment: Empatheia stores emotion histograms and numeric behavioral summaries. It explicitly does **not** store any transcript text — even `_handle_transcription()` ignores the `text` field and records only a neutral, zero-confidence emotion observation to tick the interaction count.

---

## Inputs

| Source | Stream | Event type | What is used |
|---|---|---|---|
| Audition | `audition.out` | `audition.emotion` | `category` (string), `confidence` (float), `prediction_error` (float) |
| Audition | `audition.out` | `audition.transcription` | Interaction count bump only; text ignored |

Audition events are consumed by a background `_audition_consumer_loop` task. Empatheia's `on_workspace` is a no-op placeholder for future workspace-context reactions.

---

## Outputs

| Stream | Event type | Key payload fields | Salience |
|---|---|---|---|
| `empatheia.out` | `empatheia.agent_model` | `agent_id`, `agent_label`, `familiarity`, `reliability`, `interaction_count` | Interpolated: `baseline + familiarity × (alert − baseline)` |
| `empatheia.out` | `empatheia.social_error` | `agent_id`, `agent_label`, `salience`, `deviation_magnitude` | Interpolated: `baseline + deviation × (alert − baseline)` |

`empatheia.agent_model` carries no raw behavioral data — only numeric summary fields. `empatheia.social_error` is intentionally minimal: agent id, salience, and deviation magnitude only.

---

## Configuration

All keys under `[empatheia]` and `[empatheia.qdrant]`. See also [`../configuration.md`](../configuration.md).

| Key | Default | Description |
|---|---|---|
| `backend` | `"qdrant"` | `"qdrant"` or `"inmemory"` |
| `collection` | `"empatheia_agents"` | Qdrant collection name for agent profiles |
| `speaker_label` | `"operator"` | v1 single-agent label (all observations assigned to this agent) |
| `deviation_threshold` | `0.5` | Emotion deviation above which `empatheia.social_error` fires |
| `baseline_salience` | `0.15` | Minimum event salience |
| `alert_salience` | `0.6` | Maximum event salience |
| `[empatheia.qdrant].host` | `"127.0.0.1"` | Qdrant host |
| `[empatheia.qdrant].port` | `6533` | Qdrant port |

The Qdrant API key is read from `config/secrets.toml` (`[qdrant].api_key`) — the same key used by Mnemos.

---

## How it works

### AgentModel

`kaine/modules/empatheia/agent.py` defines the per-agent social model:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Stable agent identifier (= `speaker_label` in v1) |
| `label` | `str` | Human-readable display name |
| `emotion_histogram` | `dict[str, float]` | EMA-blended frequency distribution over 8 emotion categories |
| `behavioral_summary` | `dict[str, float]` | `mean_confidence`, `mean_prediction_error` (running EMA) |
| `reliability` | `float` ∈ [0,1] | Decays on out-of-character behavior, recovers otherwise |
| `interaction_count` | `int` | Total folded observations |
| `first_seen` / `last_seen` | `float` | Unix timestamps |

**`familiarity()` formula:**
```
count_score  = 1 − exp(−interaction_count / 50.0)
coverage     = (categories seen at least once) / 8
familiarity  = (count_score + coverage) / 2.0
```
Approaches 1 monotonically; ~50 interactions → ~0.85.

**`update_from_emotion()` mechanics:**
1. Computes deviation *before* updating: `(1 − histogram[observed_category]) × confidence`.
2. EMA-blends the observed category into the histogram (`α = 0.2`).
3. EMA-updates `mean_confidence` and `mean_prediction_error`.
4. Decays `reliability` by `α` if `deviation > threshold`; recovers by `α × 0.5` otherwise.
5. Returns the deviation for the caller to decide whether to fire `social_error`.

### Emotion categories

Eight canonical categories from `audition.emotion` payloads:
`angry`, `disgusted`, `fearful`, `happy`, `neutral`, `sad`, `surprised`, `unknown`.

Unknown categories are mapped to `"unknown"` before histogram update.

### Processing flow

```mermaid
flowchart TD
    AUD[audition.emotion] --> CONS[_audition_consumer_loop]
    CONS --> HAND[_handle_emotion]
    HAND --> GET[store.get(agent_id)]
    GET --> NEW{model\nexists?}
    NEW -- no --> CREATE[AgentModel(id, label)]
    NEW -- yes --> UPD
    CREATE --> UPD[update_from_emotion\ncompute deviation]
    UPD --> PUT[store.put(model)]
    PUT --> AM[publish empatheia.agent_model]
    UPD --> DEV{deviation >\nthreshold?}
    DEV -- yes --> SE[publish empatheia.social_error]
    DEV -- no --> SKIP[no social_error]

    TRANS[audition.transcription] --> CONS
    CONS --> HT[_handle_transcription]
    HT --> NEUTRAL[update_from_emotion\nneutral, conf=0]
    NEUTRAL --> PUT
```

### Storage backends

**`InMemoryAgentStore`**: `dict[str, AgentModel]` in process. Fast; no Qdrant; lossless `serialize()`/`deserialize()` via JSON.

**`QdrantAgentStore`**: Uses the same Qdrant instance as Mnemos. Profile JSON is stored in the point payload under `"profile_json"`, keyed by `agent_id`. A behavioral summary embedding (from `all-MiniLM-L6-v2`) is stored alongside for future similarity search. A local `dict` cache avoids Qdrant roundtrips on hot-path `get()`. `serialize()` snapshots the local cache.

### Fork/merge (`EmpatheiaMergeStrategy`)

When two Eidolon forks are merged, the lifecycle subsystem calls `EmpatheiaMergeStrategy.merge(state_a, state_b)`:

- `interaction_count`: **sum** (both branches saw real interactions).
- `emotion_histogram`, `behavioral_summary`, `reliability`: **weighted average** by interaction count.
- `first_seen`: **min**; `last_seen`: **max**.

The merged profile is applied to the store via `apply_merged_state()`.

### Thymos coupling

`empatheia.agent_model` events publish `familiarity` (float ∈ [0,1]). When `[thymos.coupling].enabled = true`, Thymos reads this value and scales its affective coupling coefficient:

```
effective_coupling = coupling_base + familiarity × coupling_familiarity_gain
```

This means KAINE's emotional responsiveness to a familiar interlocutor is higher than to a stranger — the more interactions, the stronger the affective echo.

---

## Key files

| Path | Purpose |
|---|---|
| `kaine/modules/empatheia/module.py` | `Empatheia(BaseModule)` — audition consumer, event dispatch, publications |
| `kaine/modules/empatheia/agent.py` | `AgentModel` — histogram, EMA update, `familiarity()`, deviation |
| `kaine/modules/empatheia/store.py` | `AgentStore` protocol, `InMemoryAgentStore`, `QdrantAgentStore`, `EmpatheiaMergeStrategy` |
| `kaine/boot.py` | `make_empatheia()` — Qdrant sub-table wiring |

---

## Enabling and use

1. Start the Qdrant container (same as Mnemos) or set `backend = "inmemory"`.
2. Edit `config/kaine.toml`: set `[modules].empatheia = true`.
3. Optionally enable Thymos affective coupling: `[thymos.coupling].enabled = true`.

To test with a scripted agent model:

```python
from kaine.modules.empatheia.agent import AgentModel
from kaine.modules.empatheia.store import InMemoryAgentStore

store = InMemoryAgentStore()
await store.initialize()
model = AgentModel(id="operator", label="operator")
model.update_from_emotion("happy", confidence=0.9, prediction_error=0.1)
print(model.familiarity())  # ~0.067 after one interaction
```

---

## Zero-persistence note

Empatheia stores **no raw sense data**:

- `_handle_transcription()` ignores the `text` field entirely.
- `_handle_emotion()` reads only the categorical `category` string and two floats — no transcript.
- `AgentModel.to_dict()` serializes only the histogram, behavioral summary, and numeric fields.
- `empatheia.social_error` payload contains only `agent_id`, `agent_label`, `salience`, and `deviation_magnitude`.

---

## Tests

| File | Coverage |
|---|---|
| `tests/test_empatheia_agent.py` | `AgentModel` update, deviation, familiarity growth, EMA correctness |
| `tests/test_empatheia_store.py` | `InMemoryAgentStore` CRUD, `QdrantAgentStore` (mocked) |
| `tests/test_empatheia_merge.py` | `EmpatheiaMergeStrategy` weighted merge; count sum; edge cases |
| `tests/test_empatheia_module.py` | Full `Empatheia` tick; emotion → agent_model; transcription no-text; social_error threshold |

---

## Spec and related

- Primary spec: [`openspec/specs/empatheia/spec.md`](../../openspec/specs/empatheia/spec.md)
- Related modules: [Audition](audition.md) (source of `audition.emotion` events), [Thymos](thymos.md) (`familiarity` drives affect coupling), [Mnemos](mnemos.md) (shared Qdrant instance)
