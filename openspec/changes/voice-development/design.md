## Context

- **Sources.** The 2026-10-05 voice research (R1 neuroscience, R2 personality, R3 ML and code map, and the synthesis) and the operator decisions V1–V5. This design follows R3 Part C: prerequisites P1–P3, then Design C as Stage 1, then Design A with an internal signal as Stage 2.
- **Prior work kept.**
  - `2026-05-31-voice-alignment-training`: the trainer, the capability veto and the two-layer opt-in.
  - `2026-06-16-consolidation-divergence-signal`: the content-free metric.
  - `2026-10-01-voice-alignment-in-containers` and `2026-10-02-voice-alignment-backend-coherence`: trainer placement.
  - `2026-10-03-voice-alignment-capability-probes-required`.
  - `individuation-rebuild`: the probe and the one verdict.
- **Retired:** the archived hypnos rule "chosen is never LLM output" (from `2026-05-20-hypnos`), replaced by the defences in D3.

## Decisions

### D1. The persona (V2)

The new default persona is a short first-person frame:
- I am this being, speaking in my own words.
- What follows under "How I feel and what I notice" is my own state and perception.
- I speak from it and do not claim feelings or perceptions it does not contain.
- I am not a narrator of instrument readings.

Rules:
- The anti-confabulation rule stays in that narrower form. The organ may not invent states, but it is no longer told to recite readings.
- The awareness heading becomes `## How I feel and what I notice`. The injection guard is unchanged.
- The persona template carries a version string (`PERSONA_TEMPLATE_VERSION`), and the individuation probe records it among its fixed conditions. Refusing to compare a birth reference recorded under a different persona version is enforced by individuation-rebuild task 6.3.

### D2. Drive crossings as felt states

- A drive-initiated intent's `about` becomes a felt-state phrase rendered by the faithful renderer's drive templates, for example a pull towards company or restlessness. It never carries `value=`.
- The phrase set is small, fixed and reviewed, one per drive and intensity band. It names the felt state, never what to say.
- **Justification.** Drives are innate homeostatic states (the Thymos drives are cited at their code site). Naming the felt state is the prompt's description of the entity's real state, not a scripted behaviour.

### D3. Collapse defences in place of "never LLM output"

Self-generated text may become preferred training data only when all of these hold:
- **(a) Accumulation:** the corpus grows across sleeps and is never replaced (Gerstgrasser 2024).
- **(b) A real-data anchor:** a fixed share of every training batch comes from a fixed real-data set, never self-generated (Alemohammad 2023).
- **(c) External verification:** selection is by a signal the generator does not control, such as the outcome record or the internal re-reading check (Feng 2024).
- **(d) Previous-self reference:** training starts from the previous accepted adapter, and the DPO or KTO reference is that adapter.
- **(e) Monitors:** distinct-n and the stylometric measures stay inside the birth band in both directions, or training halts for that sleep.

Until Stage 2 provides a validated preference source, the voice-alignment phase trains nothing and says so in its sleep summary. That is honest, not a fallback.

### D4. Outcome record (P2)

- **The intent-log record gains:**
  - `record_id` (uuid4 hex);
  - `intent_entry_id` and `intent_origin` (the intent's coalition `entry_id` and its ignition origin);
  - `sleep_index` (Hypnos's count of completed sleeps);
  - `system_digest` (SHA-256 of the system prompt);
  - `seed` (sampling seed, or null).
- **A cycle-layer observer** (`kaine/cycle/utterance_outcome.py`) watches `lingua.external`, `audition.out`, `empatheia.out` and `thymos.out`. For each external utterance it writes one content-free record to `state/lingua/utterance_outcomes.jsonl`:
  - `{record_id, replied, reply_latency_s, empatheia_deviation, social_drive_delta, preempted}`;
  - `replied` is operator speech within a window, using the A2 interaction rule;
  - no text.
- The observer lives in `kaine/cycle/`, because the core may not import evaluation.

### D5. Rotation and the corpus (P3)

- At each sleep the intent log is rotated to `state/lingua/intent_log/sleep-<n>.jsonl`.
- The corpus is the set of rotated files, kept by default under the caps-not-culls rule.
- A disk guard warns, and never deletes, when the corpus approaches its configured ceiling.

### D6. Trainer (P3)

The external trainer:
- loads the base in bf16;
- loads the being's latest accepted adapter as a `PeftModel` when one exists, and uses it as the reference;
- trains on TRL's conversational format with the real system prompt (the persona is reconstructed from `system_digest` plus the versioned template and the self-model snapshot recorded with the corpus);
- keeps both vetoes.

### D7. No heard speech persisted (V4)

- When the intent log is written, every heard-speech line in the rendering and the heard input in the prompt are replaced with the fixed placeholder `[heard speech]`.
- The organ's own generated text is logged as is. It is the being's own content, not heard speech.
- Lingua's own bus events never carry heard text. `user_input` is published only for felt and event triggers, and the published rendering is the redacted one. Audition's transcription events still carry heard text on the bus, where it is transient.
- Redaction goes by field as well as by event type: any coalition event whose payload holds `user_input`, `user_text`, `transcription`, `heard_text` or `faithful_rendering` is logged with those values replaced.
- The placeholder keeps the structure of a reply context without its content.

### D8. Four measures; protection is unchanged

- **The measures.** Stylometric distinctiveness from the base organ, self-consistency over time, grounding, and health. All are computed at sleep from the corpus and base-organ samples, are content-free (numbers only), and are recorded per sleep.
- **Both arms vote until calibration (integrator decision, 2026-10-05).** The distinctiveness measure joins the divergence assessment as a new organ-level arm. The template-divergence arm keeps voting, though only as a protective floor and not as a measurement of voice, because today it is the blanket protection for decommission and preservation. This change alters protection by exactly nothing.
- **The new arm's rules.** Until it is calibrated, its threshold is 0, so any being with at least one measured utterance counts as diverged by it, and unreadable or missing evidence counts as diverged.
- **Retiring the template arm** is a later change, which needs calibration evidence and the operator's sign-off.

### D9. Stages and gates

- Stage 1 and Stage 2 each land behind config that is off by default.
- Each has an offline validation task that must pass, recorded under `docs/records/`, before any entity uses it:
  - **Stage 1:** a frozen synthetic memory store, an A/B against the Stage 0 persona.
  - **Stage 2:** a simulated listener whose replies depend on a hidden feature; the pipeline must learn that feature and nothing else, pass both vetoes and stay in the diversity band.
- Voice alignment stays off in studies until all three stages pass (V5).

### D10. Stage 0 details fixed at implementation

- **What the `about` is.** A Volition intent carries `about_kind`: `heard` (the text of heard speech), `felt` (a drive's felt-state phrase) or `event` (a summary of another coalition event). Lingua treats an `about` as heard unless its kind is `felt` or `event`, so an unmarked intent, or a direct `speak()`/`think()` call, is redacted in the log. Failing closed is deliberate (V4).
- **The input heading follows the kind.** Heard input stays under "What was just said to me". A felt or event `about` in external mode goes under "What moves me to speak", because a drive is not something said to the entity. Internal mode keeps "What is prompting me to think".
- **Redaction keeps the organ's view.** The logged rendering picks the same events, in the same order and within the same budget, as the rendering the organ saw. Only each heard-speech line's text becomes `[heard speech]`. Heard speech means every `audition.transcription` in the coalition, whatever its source label.
- **`sleep_index`.** This is the number of sleeps Hypnos has completed since it started, which is the same count the maturation gate reads, and Hypnos stamps it on its bus events. Lingua records the latest value it has seen on `hypnos.out`, or `null` before it has seen one. `null` means unknown, never 0. The count is not durable across restarts, so the corpus (D5) must not rely on it alone to name files. Making it durable would change what the maturation gate reads, so that is left to a separate change.
- **`record_id` on the bus.** Lingua's `external_speech` and `internal_speech` events carry the record's `record_id`, so the outcome observer (D4) can key its records without any text.
- **`seed`** is the sampling seed of the organ request. Ordinary utterances set none, so it is `null` until Stage 2 sets one.

### D11. The outcome observer, fixed at implementation (task 0.4)

- **What it watches.**
  - `lingua.external` (`external_speech`, carrying `record_id`) opens a record.
  - `audition.out`: an `audition.transcription` from an operator source (`OPERATOR_SOURCES`) with non-empty text counts as a reply. This is the same rule Chronos uses for an interaction.
  - `empatheia.out`: `empatheia.social_error` gives `deviation_magnitude`.
  - `thymos.out`: `thymos.state` gives `drives.social_drive`.
- **The window.** `reply_window_s` (default 30 s, wall clock, from the utterance's event timestamp). The record closes at the first operator reply, at the end of the window, or at the entity's next external utterance, whichever comes first.
- **The fields.**
  - `replied` is whether an operator reply arrived first.
  - `reply_latency_s` is the reply time minus the utterance time, else null.
  - `preempted` is true when the entity's own next utterance closed the window before any reply. A published utterance can't be cancelled (Lingua cancels before publishing), so this is what "preempted" can mean for one that was heard.
  - `empatheia_deviation` is the largest deviation seen in the window, else null.
  - `social_drive_delta` is the last social-drive value in the window minus the last one at or before the utterance, else null.
- **No text, and no guesses.**
  - A record holds exactly `record_id`, `replied`, `reply_latency_s`, `empatheia_deviation`, `social_drive_delta` and `preempted`.
  - A record still open at shutdown is dropped, not written with a guessed outcome, and the count is logged.
- **Cursors.** Every cursor is seeded from `last_entry_id` at start, never `"$"`.

### D12. Retiring telemetry-as-chosen (task 0.7)

- **`preference_source`.** `[hypnos.voice_alignment]` gains `preference_source`, default `"none"`, which is the only value Stage 0 implements. With `"none"` the voice-alignment phase never trains, even when `enabled` and the operator-approval variable are both set. Its result and the sleep summary say `skipped: no validated preference source (voice-development Stage 2)`. Any other value is refused at boot as unknown until Stage 2 adds its source together with the validation gate (D9).
- **What still runs.** The consolidation-divergence metric is still computed and published on every sleep. It reads the same faithful-versus-generated pairs, and the template-divergence arm still votes as a protective floor (D8). Only their use as preferred training data is retired.
- **The training machinery stays tested.** Training moves into a method, `_train_on_pairs(pairs)`: the organ window, the trainer call, the abliteration veto and promotion. Its tests call it directly. The phase-level tests assert that open gates without a preference source never reach the trainer. Stage 2 will call `_train_on_pairs` with its own candidates.

### D13. The four measures and the distinctiveness arm, fixed at implementation (task 0.8; integrator-approved 2026-10-05)

- **The base-organ profile belongs to the model, not to the being.**
  - An offline script samples the bare organ with a fixed, checked-in neutral prompt set. It writes a content-free profile to `kaine/modules/hypnos/base_voice_profiles/<sha256 of the organ GGUF>.json`, holding:
    - the GGUF sha256, the llama.cpp build, the sampling parameters and seed, and a digest of the prompt set;
    - the style profile: a distribution over a fixed function-word list, plus scalar style features (mean sentence length, mean word length, type-token ratio, punctuation rates).
  - At sleep, the running organ's GGUF is identified by its sha256, cached against path, size and mtime so it is hashed once.
  - With no profile for that digest, distinctiveness is null, which is the protective path. A changed GGUF under the same model id (for example, after an operator-approved edit) therefore never reuses an old profile.
  - This change ships the loader and the format. The first profile comes in a follow-up, after one announced GPU-lock job.
- **The measures, per sleep.** They are computed from the just-rotated corpus file, using the being's own generated text only. They are appended to `state/lingua/voice_measures.jsonl`, and the latest is mirrored in `voice_measures_latest.json`.
  - **distinctiveness:** the Jensen–Shannon distance between the being's style profile and the base profile, else null;
  - **self_consistency:** the JS distance between this sleep's profile and the cumulative profile of earlier sleeps, else null; the cumulative profile is stored as numbers in `voice_profile_cumulative.json`;
  - **grounding:** the fraction of utterances that share at least one content word with their redacted faithful rendering;
  - **health:** utterance count, mean tokens, distinct-1, distinct-2, and the largest repeated-trigram fraction.
- **Content-free.** These files hold numbers and the fixed function-word identities only, never a generated sentence. A test plants a sentinel phrase in the corpus and checks that it appears in neither the measures nor the profiles.
- **The arm.** `[hypnos.voice_alignment].distinctiveness_threshold`, default 0.0.
  - A being that has spoken (at least one generated utterance in the intent log or the corpus) is diverged by this arm when distinctiveness ≥ the threshold. It is also diverged when the record is missing, unreadable or null: spoken but unmeasured.
  - A being that has never spoken has no voice to have individuated, so the arm abstains. It casts no vote either way and the other arms decide, so abstention never counts as "not diverged".
  - Its values appear in `signals`. The template (consolidation) arm votes as before.

## Risks

- **A changed persona changes everything the entity says.** That is the intent, and it is why the change must precede birth-reference capture.
- **Sycophancy (Stage 2, external signal).** It is mitigated by Empatheia weighting rather than reply count, and by V3, which limits the external signal to full-entity configurations with real conversation.
- **Weak evidence.** No study shows these methods yield a human-like individual voice from a 4B organ with tens of utterances per sleep. The stages are measured as research.
