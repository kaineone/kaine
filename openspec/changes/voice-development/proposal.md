## Why

Voice training exists so that the entity individuates away from its language organ's original training data and develops a voice of its own. It should converse the way people do, not recite workspace statistics, and not sound like a stock LLM without KAINE's modules (operator, 2026-10-05). The 2026-10-05 voice research (three reports plus a synthesis, `kaine-voice-research-2026-10-05`) found the code works against that goal at several levels:

- **The persona forbids a voice.** The default persona orders the organ to "put the system's current internal state — the module readings given below — into plain words … Report only what the readings actually contain … do not invent feelings" (`kaine/modules/lingua/context.py`). Drive-initiated speech is prompted with literal strings such as `social_drive (value=0.83)` (`kaine/workspace/drive_policy.py`).
- **Training rewards telemetry.** The DPO "chosen" text is the templated faithful rendering, for example "Soma reports wellness 0.83, no alerts" (`kaine/modules/hypnos/voice_alignment.py`). Every sleep would push the voice toward the template. The hypnos spec requires this, as a defence against model collapse.
- **Training never builds on itself.**
  - Each sleep attaches a fresh LoRA to the base model, so the reference is always the stock organ.
  - The intent log is never rotated, so every sleep re-reads its oldest records.
  - Training uses plain text with no system prompt, while serving uses the chat template.
  - The base loads in 4-bit.
- **The divergence arm points the wrong way.** Consolidation divergence fires whenever the organ's output differs from the template, so a voice that learned to recite telemetry would *lower* it.
- **Nothing links an utterance to what happened next.**
- **Heard speech is persisted.** When transcription is on, heard speech enters the faithful rendering (`Speech heard: "…"`, `kaine/faithful/templates.py`) and the prompt (`## What was just said to me`). Both are written to `state/lingua/intent_expression.jsonl`. That breaks zero raw-sense persistence.

## What Changes

The operator approved the staged design on 2026-10-05 (decisions V1–V5). This change delivers it in three stages. Each stage is validated offline before any entity uses it.

### Stage 0: fixes that every design needs

1. **First-person conditioning (V2).**
   - The telemetry persona becomes a minimal first-person frame grounded in the entity's real states. The awareness block is headed as how I feel and what I notice.
   - Inventing states the readings do not support stays forbidden.
   - Drive crossings reach the organ as felt states rendered by the faithful renderer, never as `value=` strings.
   - The persona template carries a version, recorded wherever the individuation probe records its conditions.
2. **An outcome record per utterance.**
   - Each intent-log record gets a stable record ID, its intent link (the coalition `entry_id` and origin), the sleep index, a digest of the system prompt, and the sampling seed.
   - A content-free outcome observer in `kaine/cycle/` writes one record per external utterance: replied, reply latency, Empatheia deviation, social-drive change, preempted.
3. **Trainer hygiene.**
   - Train from the previous accepted adapter, so the reference is the entity's previous self.
   - Rotate the intent log by sleep index and accumulate a corpus of experience across sleeps.
   - Train in the chat format with the real system prompt.
   - Load the base in bf16, not 4-bit.
   - Keep both vetoes (capability loss and refusal).
4. **No heard speech persisted (V4).** The intent log never stores heard speech. The heard-speech line of the rendering and the heard input in the prompt are written as a fixed placeholder. No SPIN.
5. **Four measures replace the template-divergence arm:**
   - stylometric distinctiveness from the base organ;
   - self-consistency over time;
   - grounding: word choice tracks Thymos and Soma, and telemetry recitation falls;
   - health: lexical diversity, the capability veto, and only partial alignment with the interlocutor.

   Distinctiveness joins the divergence assessment as a new arm, with a threshold of 0 until calibrated. The template arm keeps voting as a protective floor, so protection is unchanged. Unreadable or missing evidence still counts as diverged.
6. **Spec.** The hypnos requirement that "chosen" is the faithful rendering and "never LLM output" is retired. A MODIFIED delta replaces it with the accumulation, real-data-anchor and verifier defences.

### Stage 1: speaking from memory, with no training

The organ is conditioned on its Eidolon values and norms, on Mnemos recall of its own past utterances and episodes with their affect, and on recent dialogue. This is validated offline on a frozen synthetic memory store against the Stage 0 persona, using the Stage 0 measures.

### Stage 2: learning to say what it means and to be understood

1. During sleep, sample K candidates from the entity's own organ per logged context.
2. Rank them by an internal "said what I meant" signal (re-reading the candidate recovers the intent) and, in full-entity configurations with real conversation only (V3), by listener uptake weighted by Empatheia deviation, never by raw reply count.
3. Train from the previous adapter on the accumulated corpus, with a fixed real-data anchor and collapse monitors.
4. Validate offline first, with a simulated listener that answers according to a hidden feature.

### Placement (V5)

Voice alignment stays off in studies until Stages 0–2 pass offline validation. If they pass before the module-ignition study launches, the study's final-step placement stands.

## Capabilities

### New Capabilities

- `voice-development`: the outcome record, the corpus, the stage gates and the four measures.

### Modified Capabilities

- `hypnos`: how preference pairs are formed, replacing "chosen is the faithful rendering".
- `lingua`: the persona, the awareness heading, drive crossings and the intent-log contents.

## Impact

- **Ordering.** Stage 0's persona changes the individuation probe's fixed persona. It must merge before the individuation calibration and before any birth reference is captured, and it bumps the persona-template version the probe records.
- **High-risk throughout:** voice alignment, the welfare-adjacent divergence arm, and what the entity is told it is. Qwen and Kimi first-pass reviews, then the integrator's second review.
- **Research impact.** The persona and drive rendering change every utterance the entity produces, so the next study is re-baselined. Voice alignment stays off in studies until the stages pass.
- **Paper.** Revision notes for the persona, the retired chosen-source rule and the four measures.
- **Preserved beings.** Adapters already trained remain valid. The first Stage 0 training starts from a being's latest accepted adapter, or from the base organ if it has none.
