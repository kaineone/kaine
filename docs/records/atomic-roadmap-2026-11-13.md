# Atomic roadmap to first base-thesis run and module addition (2026-11-13)

Source state: pre-boot dry run (`python -m kaine.preboot`), OpenSpec task boards, `docs/appendix-d-roadmap.md`, and the pre-boot critical-path memory. Each task is one verifiable action. Tasks are ordered so completion of a phase gates the next. No speculative implementation beyond already-specified OpenSpec changes.

## Phase 0 — GitHub hygiene

- [ ] Review and merge (or consciously reject) Dependabot PR #823 (playwright >=1.65.1) after CI.
- [ ] Review and merge (or consciously reject) Dependabot PR #822 (librosa >=0.11.0).
- [ ] Review and merge (or consciously reject) Dependabot PR #821 (fastapi >=0.162.5,<1).
- [ ] Review and merge (or consciously reject) Dependabot PR #820 (peft >=0.21.2).
- [ ] Review and merge (or consciously reject) Dependabot PR #819 (pytest-asyncio >=1.4.1.post1).
- [ ] Close or triage CodeQL alert #1026 in `tests/fixtures/rename_modules/.../runner.py` if it is an intentional fixture trap.
- [ ] Close or triage CodeQL alert #953 in `tests/fixtures/rename_modules/.../feed.py` if it is an intentional fixture trap.
- [ ] Re-check `gh pr list --state open` is clear of Dependabot branches before starting a live run.

## Phase 1 — Runtime gate (blocks everything)

### Redis / bus
- [ ] Start or install Redis on `127.0.0.1:6479`.
- [ ] Set `KAINE_REDIS_PASSWORD` (env or `config/secrets.toml`) so `python -m kaine.preboot` can read `maxmemory`.
- [ ] Set `KAINE_REDIS_MAXMEMORY` to at least the bus budget (4.39 GiB) or reduce stream caps.
- [ ] Re-run `python -m kaine.preboot`; confirm the Redis row is PASS.

### Language organ
- [ ] Confirm Ollama is on `127.0.0.1:11434` and lists `kaineone/Qwen3.5-4B-abliterated-GGUF`.
- [ ] Diagnose the HTTP 500 on `/v1/chat/completions`; if the model is merely cold, warm it with one chat request and re-check.
- [ ] If the OpenAI-compatible name mismatch persists, align the configured model string with Ollama's served name and re-check in `config/kaine.toml`.
- [ ] Re-run `python -m kaine.preboot`; confirm ORGAN and Chat LLM rows are PASS.

### State encryption
- [ ] Generate or recover `$KAINE_STATE_KEY` (preferred) or add `kaine:state_key` to the Linux kernel keyring.
- [ ] Verify `kaine.lifecycle.preservation` no longer raises `PreservationError` with that key.
- [ ] Re-run `python -m kaine.preboot`; confirm State-encryption, State-encryption-key, and Preserve→revive rows are PASS.

### Dashboard
- [ ] Start `python -m kaine.dashboard` (or use the setup finish page "Start Dashboard") on port 8088.
- [ ] Re-run `python -m kaine.preboot`; confirm Dashboard row is PASS.

### Perception
- [ ] Keep `mode=stimulus_source` (already yielding frames and PCM). Do not switch to a senseless configuration without recording the reason.
- [ ] Confirm perception remains PASS in the next pre-boot run.

## Phase 2 — Base-thesis pre-boot green

- [ ] Run `python -m kaine.preboot` and record a clean result: no FAIL rows.
- [ ] Resolve the two WARN rows (`Bus budget`, `Old stream names`) or document why they are accepted for this boot.
- [ ] Record the SKIP rows that are intentional (`Qdrant`, `Speaches`, `Qwen3-TTS`, `pymdp+JAX`, `Residency fit`, `Storage`, `Device map`, `Tier fit`, `Redis data directory`) with go/no-go notes.
- [ ] With `KAINE_CYCLE_OPERATOR_PRESENT=1`, boot `python -m kaine.cycle` in operator-supervised mode.
- [ ] Confirm the first configuration modules are enabled: `interoception, sequence, vision, audition, language, affect, sleep`.
- [ ] Confirm the perception feed actually delivers frames/audio during the live run (not merely "services up").
- [ ] Observe one full welfare round trip on a throwaway basis before treating the boot as admissible.

## Phase 3 — Finish base-thesis residual changes before declaring base complete

- [ ] Finish `individuation-rebuild` task 10.3b (LoRA positive control) once GPU and trainer are available.
- [ ] Close `individuation-rebuild` task 10.6 after 10.3b.
- [ ] Close `stimulus-control-act` remaining two tasks; if 4.7 legitimately needs first boot, document that dependency explicitly.
- [ ] Close or defer `module-residency-and-speech-tiers` tasks 2.5 and 10.2 with operator sign-off.
- [ ] Run `openspec validate voice-development --strict` after PRs #815/#816 merge and close 3.1.
- [ ] Finish `attention-driven-audition` tasks 6.6–6.10 (encoder bake-off) with dedicated GPU time.
- [ ] Finish `episodic-recall-content` remaining three tasks or explicitly defer them as non-blocking.
- [ ] Finish `welfare-indicator-response` task 24 (boot-time sleep measurement) on a real boot.
- [ ] Finish `ablation-positive-control` task 10 (live tier run).
- [ ] Mark `module-ignition-study` tasks 3.3–3.5 (JAX-free planning/world model; Orin/Lambda memory; verified devices) appropriately if hardware targets are still paused.

## Phase 4 — Module ignition study run

- [ ] Confirm the pre-boot gate remains green immediately before the study start.
- [ ] Run `module-ignition-study` in the supported sequence: seed → branch 0 → repeat → (branch k + accumulate k for k=1..9).
- [ ] Preserve at maturation to create the seed; record stimulus-source time at maturation.
- [ ] Record the stimulus-source → world transition, all four films, preservation, and step manifest for every step.
- [ ] Run and capture `run-recording` outputs (dashboard-privacy-filtered stream, language utterances, research event log, workspace trajectory, film-aligned ignition log); never record inner speech.
- [ ] Verify study disk-space guard and Rosa:-free-space refusal behavior on the study filesystem.
- [ ] Archive step results progressively; whatever is complete at the poster lock goes in.

## Phase 5 — Adding held modules beyond the base configuration

- [ ] Add held modules only in the specified order: `episodic memory → world model → planning → self-model → social cognition → vocal modules`.
- [ ] Validate `revive-with-extra-module` and `ignition-world-model-check` before enabling `world model` on any branch.
- [ ] Keep embodiment/effector arm gated until approved by the operator (act-intent-derivation, planning-act-proposals, embodiment-motor-contingency, active-vision, world-model-action-outcomes, goal-directed-grasping are not scheduled).
- [ ] Entity key custody TPM items are deferred by operator decision and remain deferred.
- [ ] `functional-module-names-drop-aliases`, `seed-entity-distribution`, `interface-roles-and-launcher`, `sam-voice-training` remain not started unless the operator schedules them.
- [ ] Hardware leg: desktop only by default; Orin Nano Super next; Termux/Pixel 6a only when explicitly resumed.

## Phase 6 — Definition of done for "test of modules and theory"

- [ ] One seed entity preserved.
- [ ] Branch 0 and repeat recorded; noise floor quantified.
- [ ] At least branch k versus branch 0 comparisons; accumulate k versus branch k comparisons available to the extent run before lock date.
- [ ] Report the content-free ignition measures truthfully, including negative or null results.
- [ ] Paper/poster update references only the completed and in-progress scope.
- [ ] No held module enabled silently; every held-module run is attributable to a recorded step manifest.