# Re-review: `build/operator-speech` and `conversation-memory` against main (2026-11-21)

Operator request, 2026-11-20: re-review and split `build/operator-speech`, then
re-review `conversation-memory` against current main and option F, so heard
words can reach the latent workspace with biologically grounded memory.

Main at the time of review: after #849 (the #829 revert) and #848.

## 1. `build/operator-speech`

56 commits, branched 2026-11-01 at `d7fabdc0a`; main is 203 commits ahead.
No commit is patch-equivalent to main. The commits form four OpenSpec changes.

| Group | Change | On main? | Verdict |
|---|---|---|---|
| G1 | episodic own-content and media-name privacy (12 commits) | Yes, evolved: #636, #639; 9 of 25 files identical | Superseded. Nothing to port. |
| G2 | `latent-content-privacy` (13 commits, 42 files) | No. Main has a lighter interim rule (`2026-11-04-latent-content-privacy-rule`: an empty `LATENT_CONTENT_FIELDS` name set) | Port. The branch design carries the operator rulings of 2026-11-01 (Q1 option B: latent values never enter a persisted bus stream; Q2 option (b)) and supersedes the interim rule. |
| G3 | `heard-text-volatile-bus` (25 commits, 86 files) | No | Port, split. |
| G4 | `operator-speech-as-perception` (4 commits, 62 files) | No. The forcing rule is still on main: `_user_utterance` and `_user_response_intent` in `kaine/workspace/action_selection.py` turn heard speech into a reply intent | Port. |

### Findings that change the port

1. **Option F landed after the branch.** #658 publishes `content: {z_k, predictions, losses}` from the feedback head (`kaine/workspace/feedback.py`). `content` is in `CONTENT_FIELDS`, so a name-based strip catches it, but under G2's provenance rule `z_k` and the decoded predictions are latent-derived values and must travel under `latent_derived`. G2's port must tag them; the branch could not.
2. **Main's interim rule must be replaced, not merged.** G2 defines `LATENT_FIELDS` and a reserved `latent_derived` key; main defines `LATENT_CONTENT_FIELDS`. The port removes the interim constant and moves its test guards to the provenance rule.
3. **Perceptual latents reach the persisted bus today.** Main's bus client does not strip latents on publish. G2 (producers strip before the main bus) and G3 (the volatile instance) close this.
4. **Encryption fails closed.** G2 makes a latent producer refuse to start without state encryption and `[preservation].require_encryption`. Option F is a latent producer, so enabling it will require encryption. Per-entity custody is still off on main (see the parked paper-queue review); state encryption is the operator-level key.
5. **G4 still matches main.** The forcing rule is present, and shipped `[action_selection]` does not name a policy, so the default policy answers heard speech. G4 makes `self_initiated_report` the shipped layer and refuses other names except `drive_biased`.

### Split plan (atomic PRs, each ported to current main, each with tests)

Order follows the dependencies. Each PR stays inside the pr-scope guard (15 commits, 40 files). Privacy PRs get a second review.

- **G2-1** latent rule, tag and `strip_latent` in `kaine/privacy_filter.py`; the interim `LATENT_CONTENT_FIELDS` retired; tests.
- **G2-2** every JSONL record loses latent fields before encoding (persistence strip); tests.
- **G2-3** renderers never format a latent field; the broadcast drops members' `latent_derived`; option F's `z_k` and predictions move under `latent_derived`; tests.
- **G2-4** content-free buffer summaries (vision, audition); module-state capture strips latents; tests.
- **G2-5** latent-producer boot check (rule plus encryption); tests.
- **G3-1** companion streams on a never-persisted Redis instance; boot, preboot and compose check; tests.
- **G3-2** decommission flushes the volatile instance with the entity's streams; tests.
- **G3-3** declared age bounds and the exact periodic sweep; tests.
- **G3-4** heard and spoken words travel only on the volatile bus; declared consumers join; the spoken-text canary.
- **G4-1** the forcing rule removed; the named report policy shipped; refusal of other policy names.
- **G4-2** the content-free operator-speech readout; the off switch stays `[audition].transcription_enabled`.

## 2. `conversation-memory` (branch `spec/conversation-memory-2026-11-01`, design only)

The design (491 lines) is sound in method: verbatim wording held seconds, the
entity's own comprehension kept, memory organised by conversation, forgetting
by level, an overlap guard, encrypted storage. Its code facts are cited at
`d7fabdc0` and must be re-cited. Changes needed:

1. **Dependencies.** `episodic-recall-content` PRs 2 and 3 are on main (29 of 32 tasks). The others are G2, G3 and G4 above.
2. **Option F.** The design sends the gist through the workspace as a `comprehension` event that competes for access (its W4). It predates the content level, so it does not say whether comprehension enters `z_k`. Language is option F's one unpaired modality (the translation-loss arm is its route). Decide: a comprehension event carries a text embedding as its latent, encoded into `z_k` like any processor's, under the latent rule (G2) and the identity rules for learned weights. Without it, conversation reaches the content level only through other processors' responses.
3. **Compression over time (operator, 2026-11-20).** The design keeps conversation traces out of associative replay and schemas until the episodic backend is encrypted (its P1, task 7.2), because a link vector or schema centroid would leak gist into plaintext Qdrant. Evidence for the operator's direction:
   - Transformation of episodic memory towards gist and schema over time is well supported (Winocur and Moscovitch 2011; complementary learning systems, McClelland et al. 1995).
   - Sleep's specific contribution is moderate: g = 0.44, bias-adjusted 0.28 (Berres and Erdfelder 2021, already in the design). Sleep-specific gist extraction remains a hypothesis.
   - Human reconsolidation is contested (Elsey et al. 2018); the design's no-rewrite rule stands.

   So: encrypt the episodic backend, then let conversation gists join consolidation into schemas. Present that as transformation over time, with sleep as one moderate contributor, not as an established sleep effect.
4. **When transcription starts.** In the developmental phase the hearing band leaves speech as prosody, so there are no words to transcribe. G4 already blocks operator speech-to-text before the last module joins. The design should name the developmental gate explicitly: transcription off until the hearing band is open and maturation is reached.
5. **Privacy stance.** The operator accepted on 2026-11-20 that heard words reach the latent workspace. The design is consistent with that: words live seconds in process and on the volatile bus, and what persists is the entity's own understanding, never a transcript.

Citations above are from the design or well-known primary sources. Every
citation is checked against the source before it goes into the revised design.
