# Empatheia

Empatheia is KAINE's social-cognition module. It tracks per-agent theory-of-mind models, familiarity, and social prediction-error salience. This page is for operators enabling the module, tuning its thresholds, or wiring it into Thymos affect coupling.

## Status

Empatheia is implemented and tested, but ships disabled: `[modules].empatheia = false` in `config/kaine.toml`. It stays gated behind a positive base-thesis result; see [Architecture](../02-architecture/README.md).

- Consumes `audition.emotion` and `audition.transcription` from Audition.
- Production backend: Qdrant, sharing the same instance as Mnemos; collection `empatheia_agents`.
- Test/minimal backend: `InMemoryAgentStore` (`backend = "inmemory"`), no external services.
- Speaker diarization is at v1: operator-facing sources are mapped to one agent label, and other sources get their own `media:<source_label>` agent.

## Responsibility

Empatheia maintains probabilistic models of agents KAINE interacts with, and signals when an agent's behaviour deviates from its established pattern.

It produces two outputs:

1. **`empatheia.agent_model`** — numeric metadata about a known agent: familiarity, reliability, interaction count. It is published on every update. The familiarity score feeds directly into Thymos affect coupling when `[thymos.coupling].enabled = true`.
2. **`empatheia.social_error`** — a salience-only signal published when an observed emotion deviates beyond `deviation_threshold`. It enters the Syneidesis workspace and raises attention by salience alone. It carries no raw behavioural data and no transcript text.

Empatheia stores only emotion histograms and numeric behavioural summaries. It never stores transcript text. Even `_handle_transcription()` ignores the `text` field and EMA-blends a neutral, zero-confidence observation into the histogram with α = 0.2, ticking the interaction count.

`Empatheia.on_workspace()` is a no-op placeholder for future workspace-context reactions.

## Inputs

| Source | Stream | Event type | Fields used |
|---|---|---|---|
| Audition | `audition.out` | `audition.emotion` | `category`, `confidence`, `prediction_error`, `source_label` |
| Audition | `audition.out` | `audition.transcription` | `source_label`; the `text` field is ignored |

Audition events are consumed by a background `_audition_consumer_loop` task. Emotion events marked `degraded = true` are skipped.

## Outputs

| Stream | Event type | Key payload fields | Salience |
|---|---|---|---|
| `empatheia.out` | `empatheia.agent_model` | `agent_id`, `agent_label`, `familiarity`, `reliability`, `interaction_count` | `baseline_salience + familiarity × (alert_salience − baseline_salience)` |
| `empatheia.out` | `empatheia.social_error` | `agent_id`, `agent_label`, `salience`, `deviation_magnitude` | `baseline_salience + deviation_magnitude × (alert_salience − baseline_salience)` |

`empatheia.agent_model` carries no raw behavioural data — only numeric summary fields. `empatheia.social_error` is intentionally minimal: agent id, salience, and deviation magnitude only.

## Configuration

All keys are under `[empatheia]` and `[empatheia.qdrant]`. The full reference is in [Modules](../appendix-a-configuration/modules.md).

| Key | Default | Description |
|---|---|---|
| `backend` | `"qdrant"` | `"qdrant"` or `"inmemory"` |
| `collection` | `"empatheia_agents"` | Qdrant collection name for agent profiles |
| `speaker_label` | `"operator"` | Label for the operator-facing agent |
| `operator_sources` | `["live_mic", "microphone", "remote"]` | Sources mapped to the operator agent; other sources become `media:<source_label>`. Also used by Volition to decide which Audition sources are user utterances. |
| `deviation_threshold` | `0.5` | Emotion deviation above which `empatheia.social_error` fires |
| `baseline_salience` | `0.15` | Minimum event salience |
| `alert_salience` | `0.6` | Maximum event salience |
| `[empatheia.qdrant].host` | `"127.0.0.1"` | Qdrant host |
| `[empatheia.qdrant].port` | `6533` | Qdrant port |
| `[empatheia.qdrant].api_key` | (unset) | Qdrant API key; also reads `KAINE_QDRANT_API_KEY` |

## How it works

### AgentModel

`kaine/modules/empatheia/agent.py` defines the per-agent social model:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Stable agent identifier |
| `label` | `str` | Human-readable display name |
| `emotion_histogram` | `dict[str, float]` | EMA-blended frequency distribution over eight emotion categories |
| `behavioral_summary` | `dict[str, float]` | `mean_confidence`, `mean_prediction_error` running EMA |
| `reliability` | `float` ∈ [0,1] | Decays on out-of-character behaviour, recovers otherwise |
| `interaction_count` | `int` | Total folded observations |
| `first_seen` / `last_seen` | `float` | Unix timestamps |

**Familiarity formula:**

```
count_score  = 1 − exp(−interaction_count / 50.0)
coverage     = (categories seen at least once) / 8
familiarity  = (count_score + coverage) / 2.0
```

Familiarity approaches 1 monotonically. `count_score` reaches about 0.63 after 50 interactions; with all eight emotion categories seen at least once, the maximum familiarity is about 0.82.

**`update_from_emotion()` mechanics:**

1. Compute deviation before updating: `(1 − histogram[observed_category]) × confidence`.
2. EMA-blend the observed category into the histogram (`α = 0.2`).
3. EMA-update `mean_confidence` and `mean_prediction_error`.
4. Decay `reliability` by `α` if `deviation > threshold`; recover by `α × 0.5` otherwise.
5. Return the deviation so the caller can decide whether to fire `social_error`.

### Emotion categories

Eight canonical categories from `audition.emotion` payloads:

`angry`, `disgusted`, `fearful`, `happy`, `neutral`, `sad`, `surprised`, `unknown`.

Unknown categories are mapped to `"unknown"` before the histogram update.

### Processing flow

```mermaid
flowchart TD
    AUD[audition.emotion] --> DEG{degraded?}
    DEG -- yes --> SKIP_DEG[ignore event]
    DEG -- no --> SRC{source in operator_sources?}
    SRC -- yes --> OP_ID[agent_id = speaker_label]
    SRC -- no --> MED_ID[agent_id = media:source_label]
    OP_ID --> GET
    MED_ID --> GET
    GET[store.get(agent_id)] --> NEW{model exists?}
    NEW -- no --> CREATE[AgentModel(id, label)]
    NEW -- yes --> UPD
    CREATE --> UPD[update_from_emotion compute deviation]
    UPD --> PUT[store.put(model)]
    PUT --> AM[publish empatheia.agent_model]
    UPD --> DEV{deviation > threshold?}
    DEV -- yes --> SE[publish empatheia.social_error]
    DEV -- no --> SKIP_SE[no social_error]

    TRANS[audition.transcription] --> SRC2{source in operator_sources?}
    SRC2 -- yes --> OP_ID2[agent_id = speaker_label]
    SRC2 -- no --> MED_ID2[agent_id = media:source_label]
    OP_ID2 --> HT
    MED_ID2 --> HT
    HT[_handle_transcription] --> NEUTRAL[update_from_emotion neutral, conf=0, α=0.2]
    NEUTRAL --> PUT
```

### Storage backends

**`InMemoryAgentStore`**: an in-process `dict[str, AgentModel]`. It needs no Qdrant and supports lossless `serialize()`/`deserialize()` via JSON.

**`QdrantAgentStore`**: uses the same Qdrant instance as Mnemos. Profile JSON is stored in the point payload under `"profile_json"`, keyed by `agent_id`. A behavioural-summary embedding from the shared `[embedding]` embedder (`all-MiniLM-L6-v2`, 384-dim) is stored alongside for future similarity search. A local `dict` cache avoids Qdrant round-trips on hot-path `get()`. `serialize()` snapshots the local cache.

### Fork and merge

`kaine/modules/empatheia/store.py` provides `EmpatheiaMergeStrategy.merge(state_a, state_b)` for combining agent-model state:

- `interaction_count`: **sum** — both branches saw real interactions.
- `emotion_histogram`, `behavioral_summary`, `reliability`: **weighted average** by interaction count.
- `first_seen`: **min**; `last_seen`: **max**.

`apply_merged_state()` writes the merged state back to the store. Nothing in the fork and merge code calls these helpers yet, so a fork merge does not combine Empatheia state through them.

### Thymos coupling

`empatheia.agent_model` events publish `familiarity` as a float in `[0, 1]`. When `[thymos.coupling].enabled = true`, Thymos reads it and scales its affective coupling coefficient:

```
effective_coupling = coupling_base + familiarity × coupling_familiarity_gain
```

The result is clamped to `[thymos.coupling].coupling_ceiling` (default `0.15`). Familiar interlocutors produce stronger affective coupling than strangers. See [Thymos](thymos.md) for the coupling configuration.

## Key files

| Path | Purpose |
|---|---|
| `kaine/modules/empatheia/module.py` | `Empatheia(BaseModule)` — audition consumer, event dispatch, publications |
| `kaine/modules/empatheia/agent.py` | `AgentModel` — histogram, EMA update, `familiarity()`, deviation |
| `kaine/modules/empatheia/store.py` | `AgentStore` protocol, `InMemoryAgentStore`, `QdrantAgentStore`, `EmpatheiaMergeStrategy` |
| `kaine/boot.py` | `make_empatheia()` — Qdrant sub-table wiring |

## Enabling and use

1. Start the Qdrant container (the same one used by Mnemos) or set `backend = "inmemory"`.
2. Edit `config/kaine.toml` and set `[modules].empatheia = true`.
3. Optionally enable Thymos affective coupling: `[thymos.coupling].enabled = true`.

To test with a scripted agent model:

```python
from kaine.modules.empatheia.agent import AgentModel
from kaine.modules.empatheia.store import InMemoryAgentStore

store = InMemoryAgentStore()
await store.initialize()
model = AgentModel(id="operator", label="operator")
model.update_from_emotion("happy", confidence=0.9, prediction_error=0.1)
print(model.familiarity())  # ~0.072 after one interaction
```

## Zero-persistence note

Empatheia stores no raw sense data:

- `_handle_transcription()` ignores the `text` field and moves the histogram toward neutral via EMA (α = 0.2).
- `_handle_emotion()` reads only the categorical `category` string and two floats — no transcript.
- `AgentModel.to_dict()` serializes only the histogram, behavioural summary, and numeric fields.
- `empatheia.social_error` payload contains only `agent_id`, `agent_label`, `salience`, and `deviation_magnitude`.

## Tests

| File | Coverage |
|---|---|
| `tests/test_empatheia_agent.py` | `AgentModel` update, deviation, familiarity growth, EMA correctness |
| `tests/test_empatheia_store.py` | `InMemoryAgentStore` CRUD, `QdrantAgentStore` (mocked) |
| `tests/test_empatheia_merge.py` | `EmpatheiaMergeStrategy` weighted merge; count sum; edge cases |
| `tests/test_empatheia_module.py` | Full `Empatheia` tick; emotion → agent_model; transcription no-text; social_error threshold |

## Spec and related

- Primary spec: `openspec/specs/empatheia/spec.md`
- Related modules: [Audition](audition.md) (source of `audition.emotion` events), [Thymos](thymos.md) (familiarity drives affect coupling), [Mnemos](mnemos.md) (shared Qdrant instance)
