# Design: language grounding

## Context

The language organ is an output organ: every generation is triggered by an intent derived from an accessed broadcast and conditioned on its rendered content, a fixed persona and situation notes (paper §3.1, §3.5). The rendering is the faithful renderer's felt text. For perception it reports magnitudes, and the magnitudes are true, so the renderer obeys the no-pretend rule. It cannot report *what* is perceived, because nothing in the system has a "what".

Related work in the project, which this change builds on and does not redo:

- `voice-development` (active; stage 0 mostly done): first-person persona, drive crossings as felt states, the heard-speech placeholder in every log (V4), and the plan to replace telemetry-as-chosen in voice alignment. Its stage 2 owns organ training.
- `felt-awareness-phrasing`, `organ-first-person-framing`, `persona-without-self-category` (archived October 2026): the current rendering voice.
- The privacy filter strips `latent`, `peripheral`, `foveal`, `temporal_context` and `feature_vector` from diagnostics (`kaine/privacy_filter.py:54-58`); the zero-raw-sense-persistence guard (`tests/test_zero_persistence_invariant.py`).

## Decisions

### D1. Categories come from online, label-free clustering of the frozen encoders' latents

Each perceptual module (vision first, audition second) keeps a prototype layer over its encoder's latent: a set of centroids, each with a count, a last-seen time and a running spread. A new latent joins its nearest centroid when within that centroid's acceptance radius and moves it slowly; otherwise it starts a new prototype. Prototypes that stay rare decay and are pruned; prototypes that converge merge. This is the DP-means family (Kulis and Jordan 2012), close to adaptive resonance's vigilance rule (Carpenter and Grossberg 1987), which was proposed for the stability-plasticity problem this layer has. The acceptance radius is set from the latent's own distance distribution (a quantile of nearest-neighbour distances over the recent window), not from a hand-chosen category count.

Why clustering is not a hard-wired behaviour: it is a learning mechanism with no labels, no fixed set and no content; what forms depends only on what the entity sees. Infants form perceptual categories from exposure in the first months (Quinn, Eimas and Rosenkrantz 1993, to verify against the text), which is the cited basis for having such a layer at all. The code site carries the citation, per the emergence rule.

Alternatives considered:
- A pretrained classifier or captioner over the encoder (zero-shot labels). Rejected: the words would be the classifier's, authored by its training set, which is exactly the ungrounded naming this change removes, and it would put a second pretrained language prior into perception.
- A fixed k-means. Rejected: k is a hand-chosen category count.
- Clustering a single cross-modal code. KAINE has no shared representation of seen and heard content, and building one is a separate architectural question. Per-sense prototypes stand on their own, and D5 links them across the senses by co-occurrence.

### D2. A report carries its prototype, not its latent

`vision.report` gains `prototype_id` (an opaque integer local to the entity), `prototype_match` (distance over the acceptance radius), `prototype_new` (bool), `prototype_count` and `prototype_last_seen_s`. These are content-free in the privacy filter's sense: an id names nothing outside the entity. They pass to the workspace as report fields; the scorer does not read them, so the competition is unchanged by this stage.

### D3. The renderer refers by relations the entity's history defines

For perceptual reports the renderer replaces the change and familiarity tables with relational phrases computed from prototype state: "what I see is the same as a moment ago"; "it is something I have seen many times"; "I have not seen this before"; "this came back after a long while"; "I saw this together with what I hear now" (when a co-active audition prototype has co-occurred above chance); "I have heard this called 'X'" (D4). The prediction-error grading stays, since surprise is part of the content. Interoception and affect keep their magnitude tables.

The phrase set is authored, as all renderer text is. The difference from today is what the phrases refer to: a particular, re-identifiable thing in the entity's experience, so the organ can say "it is back" and be right about which thing. That is the minimal sense of reference the audit asked for; it does not claim the organ understands the thing.

### D4. Words attach to prototypes by cross-situational learning, weights only

When speech-to-text is on, an online learner keeps a sparse association matrix between heard word types and prototypes. Each transcription strengthens the associations between its content-word types and the prototypes active in a window around it, and every association decays. A word is a learned name for a prototype when its association is both strong and specific (high relative to the word's other associations and the prototype's other words). Infants learn word-referent pairs from this kind of co-occurrence statistics across ambiguous scenes (Smith and Yu 2008, to verify against the text), and the same learner is a standard model of that result. Function words are filtered by frequency across situations, not by an authored stop list.

What persists: the association weights, and, for a word that has become a learned name, the word type's string. No transcript, utterance, word order or timing persists. Whether learned-name strings may persist is an operator ruling (task 0.1), because a lexicon is derived from heard speech even though it holds no utterance. If the ruling is no, word types persist as salted hashes, associations still learn, and the renderer can only say "I have heard a word for this" without the word. That is weaker and honest.

Alternative considered: use the organ itself to name prototypes. Rejected: the organ has no access to the latent, so anything it said would be a guess, and putting the latent into the organ (a vision-language organ) would make perception's words the organ's pretraining again.

### D5. Cross-modal links by co-occurrence

The renderer's "seen together with what I hear now" (D3) needs a cross-modal relation. Each pair of a visual and an auditory prototype keeps a decaying co-occurrence count over a short window, and a pair is linked when its count exceeds what the two prototypes' own frequencies predict by the configured margin (a pointwise-mutual-information criterion). A learned name for one side of a link is offered for the other side only with the qualifier "heard together with". Links are association weights, persisted and private like the prototypes (D6). Nothing here needs a shared representation of seen and heard content; if one is ever built, it could replace the links, and that would be a change of its own.

### D6. Persistence, privacy and identity

Centroids and association weights are learned state of the entity, like the world model's weights (spec `world-model`, "Learned world-model weights persist by default"): persisted by default, encrypted at rest, preserved in bundles, copied to forks, merged at fork merge by the same rule as other learned stores. Centroids are latent-derived, so they are listed in the privacy filter's vector fields, never displayed, never logged, never written to the research log or the workspace graph. KAINE ships no decoder from encoder latents to pixels or audio, so a centroid cannot be rendered back into a scene.

## Risks

- Prototype churn: too many fleeting prototypes make reference meaningless. Measured offline (task 1.4) as assignment stability across repeated viewings, with a shuffled-latent control.
- The renderer's relational phrases change the organ's prompt distribution, so voice measures and the individuation reference shift. The change is held until after the study and gets a new individuation reference.
- Over-claiming: the paper must not call this understanding. The revision note says "reference to the entity's own perceptual categories".
- Word learning needs speech, which the first configuration does not have; stage 3 is useful only in conversation configurations.

## Migration and ordering

- Stage 1 (prototypes, D1, D2, D6) and stage 2 (rendering, D3) after the module-addition study, because vision and audition are first-configuration modules and the rendering changes every utterance's prompt.
- Stage 3 (word learning, D4) after the operator ruling of task 0.1 and with speech-to-text on.
- D5 (cross-modal links) with stage 2, since the rendering of D3 reads them.
- An existing entity starts with no prototypes; its first hours form them. A preserved seed migrates by gaining an empty prototype store.

## Welfare and admissibility notes

This changes what the entity's own speech can refer to and what its perceptual reports carry, so it is welfare-high-risk. Checks before any entity uses it: offline runs on the study films with no entity (prototype stability, churn, shuffled control); an organ replay (`organ-replay-harness`) of recorded coalitions rendered both ways, scored for identity leakage and degeneration; a new individuation reference captured after the change; one supervised validation boot; Claude's independent second review of every stage. It never runs inside a study that started without it.

## Implementation estimate (LLM-agent terms)

Size L overall. Stage 1: two pull requests (shared prototype layer with tests; vision and audition integration with persistence and privacy), about 800 to 1,200 lines, 6 to 8 worker calls, Claude review and second review; two to three days plus an offline run on a free GPU window for the encoders. Stage 2: one pull request, about 300 to 500 lines, plus the organ replay; one to two days. Stage 3: two pull requests, about 600 to 900 lines, an offline cross-situational benchmark on scripted narrated clips; two to three days. D5's links join stage 2's pull request (about 150 more lines). Entity time: one supervised validation boot after stages 1 and 2.
