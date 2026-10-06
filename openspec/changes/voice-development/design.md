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
- Redaction goes by event type and by field. Every text value of an external-input event (`EXTERNAL_INPUT_TYPES`: `audition.transcription`, `mundus.chat`, one shared definition also used by the ignition audit) is heard input. On every other event, the heard-speech fields are redacted at any depth.
- The placeholder keeps the structure of a reply context without its content.
- The A/B divergence sidecar measures only felt- and event-triggered replies. Replies to heard speech carry no `user_input`, so they are recorded as content-free skips (`no_user_input_heard_reply`), not measured. Studies are unaffected, because evaluation is off in studies.

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

## Risks

- **A changed persona changes everything the entity says.** That is the intent, and it is why the change must precede birth-reference capture.
- **Sycophancy (Stage 2, external signal).** It is mitigated by Empatheia weighting rather than reply count, and by V3, which limits the external signal to full-entity configurations with real conversation.
- **Weak evidence.** No study shows these methods yield a human-like individual voice from a 4B organ with tens of utterances per sleep. The stages are measured as research.
