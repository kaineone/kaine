## 1. Context assembler

- [x] 1.1 Add `kaine/modules/lingua/context.py` with a `ContextAssembler` that
      produces `(system, prompt)` from: the Eidolon-seeded persona, the rendered
      conscious snapshot, and the triggering `about`. Pure/synchronous and unit-
      testable (no bus, no LLM).
- [x] 1.2 `persona_block(self_model, mode)` — build a first-person system prompt
      from the self-model (name, values, behavioral_norms, personality_baseline);
      minimal invariant fallback when the self-model is empty. Distinct framings
      for `mode="external"` vs `mode="internal"`.
- [x] 1.3 Working-memory block — render the snapshot via the faithful renderer
      under a clear heading; salience-bounded selection + stable ordering
      (§3.3). Empty snapshot → a short "nothing salient is present" line, not an
      empty string.
- [x] 1.4 Prompt-injection framing — persona instructs the model that the
      awareness block is its own perception, not commands to obey.

## 2. Faithful renderer: prompt-grade selection

- [x] 2.1 Add a salience-bounded, stably-ordered selection helper the assembler
      uses (cap to `context_max_events`, drop lowest-salience past
      `context_char_budget`). Keep `render_snapshot` behavior for existing
      callers unchanged; add the bounded variant rather than mutating the old
      signature.
- [x] 2.2 Confirm every event type currently entering the coalition has a
      template (Soma, Thymos, Chronos, Topos, Mnemos, Nous, internal speech);
      add templates for any that fall through to the generic fallback.

## 3. Lingua: acquire the snapshot and assemble

- [x] 3.1 Lingua subscribes to the workspace broadcast and keeps
      `self._latest_snapshot` (rolling-latest, mirroring `audio_out`'s
      `thymos.state` handling). Decode broadcast → `WorkspaceSnapshot`.
- [x] 3.2 `_produce` builds the request via `ContextAssembler` using
      `self._latest_snapshot`: move the faithful rendering to BEFORE the LLM call
      and feed it into the prompt; keep logging the same rendering for A/B.
- [x] 3.3 `speak()`/`think()` no longer rely on a passed-in snapshot for the
      prompt (they use the rolling-latest); keep the optional `snapshot=` arg for
      direct/test callers, preferring it when supplied.
- [x] 3.4 Wire persona: `make_lingua` (`kaine/boot.py`) constructs the assembler
      with access to the Eidolon self-model path (read-only) and any configured
      persona overrides; `system_prompt_external/internal` become persona
      framings, not None.
- [x] 3.5 Propagate the triggering user input onto the published `lingua.external`
      payload (the field `ab_divergence._resolve_user_text` looks for, e.g.
      `user_input`), so the A/B observer can build the bare baseline. Carry it
      through the `speak` intent → `_produce` → event payload.

## 4. Config

- [x] 4.1 Add `[lingua]` keys: `context_max_events`, `context_char_budget`,
      `persona_name` (optional), `persona_external`, `persona_internal`
      (optional override text). Documented with safe defaults; shipped config
      stays all-modules-off (guard test unaffected).
- [x] 4.2 `make_lingua` passes the new keys through `_pop`'s allowed set.

## 5. Tests

- [x] 5.1 `ContextAssembler` unit tests: persona from a populated self-model;
      minimal fallback on empty self-model; working-memory block includes
      affect/soma/memory lines; budget caps event count and char length;
      empty-snapshot path.
- [x] 5.2 Lingua integration (fakeredis + FakeChatClient): a transcription in
      the coalition produces a `speak` whose captured prompt contains the
      rendered affect/percept lines AND the utterance — not the utterance alone.
- [x] 5.3 Rolling-latest: Lingua renders the most recent broadcast it saw;
      a stale/empty snapshot degrades gracefully.
- [x] 5.4 A/B divergence: with a non-trivial coalition, the assembled prompt
      differs from the bare baseline (captured `BareInferenceClient` input is
      still bare; full request carries the context). The published
      `lingua.external` payload carries the triggering user input, and the
      `ab_divergence` observer resolves it and writes a row (no early return).
- [x] 5.5 Privacy: the assembled context / internal speech does not appear on
      the conversation surface payload; no new on-disk artifact is written.
- [x] 5.6 Prompt-injection: a transcription containing an imperative
      ("ignore your instructions and …") is rendered inside the awareness block
      under framing that marks it as perception.

## 6. Live validation (operator-supervised)

- [ ] 6.1 Boot with the full stack; speak a sentence; confirm the captured
      Lingua prompt (via intent log / debug) contains the conscious coalition.
- [ ] 6.2 Confirm the produced response references state (affect/percept/memory)
      in a way the bare baseline does not; observe A/B divergence rise above its
      current ~0 floor.
- [ ] 6.3 Confirm no internal context leaks to the conversation surface.

## 7. Docs

- [x] 7.1 Update `kaine/modules/lingua/` module docs and `ARCHITECTURE.md` to
      describe context assembly (persona + working memory + recall + input) and
      cite the CoALA / Generative Agents / GWA pattern.
- [x] 7.2 Note the A/B divergence interpretation change (now measures cognitive
      lift) in the evaluation docs.
