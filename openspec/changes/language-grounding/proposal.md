## Why

Everything the language organ is told about perception is a graded label for the size of a number. The faithful renderer maps vision's change score, habituation score and normalised error onto authored word tables (`CHANGE_WORDS`, `FAMILIARITY_WORDS`, `PREDICTION_ERROR_WORDS`, `kaine/faithful/felt.py:26-29`), so a vision report reaches the organ as "What I see is changing noticeably, feels new to me, is unexpected" (`felt.py:129-140`), audition likewise (`felt.py:143-151`), and a tone event as "A voice I hear sounds {category}" (`felt.py:374-376`). The 768-dimensional visual latent is on the bus in every `vision.report` (`kaine/modules/vision/module.py:750-751`) and stops there: no module categorises what is seen or heard, and the renderer reads only the scalars. The revised paper states the consequence: "The organ's words about perception are graded labels for the size of prediction errors, so nothing the entity perceives can be named, and the first configuration does not address symbol grounding (Harnad 1990)" (§9).

Language comprehension does not help yet. Speech-to-text is off in the first configuration (`config/profiles/first_configuration.toml:75`). When it is on, heard words reach the organ's prompt for that turn (`kaine/faithful/templates.py:301-305`) and are never persisted (voice-development decision V4), and the social cognition module ignores the text (`docs/09-modules/social-cognition.md`). No heard word can change any learned state. The organ's weights are frozen apart from the planned KAINE-only adapter.

Harnad (1990) defines grounding as connecting symbols to the sensorimotor categories they pick out. KAINE has no categories to connect to. This change designs the path: categories that emerge from the entity's own perception, a rendering that refers to them instead of to error magnitudes, and word learning that binds heard words to them. It is audit E10 (with E16) and triage workstream W5.

## What Changes

A staged design. Each stage is validated offline before any entity uses it.

1. Emergent perceptual prototypes. Each perceptual module clusters its frozen encoder's latents online into prototypes, with no labels and no fixed number. A report carries the prototype it matched, how well, and whether it was new. Prototype centroids persist as learned weights, encrypted, part of the entity's identity; no latent is logged or stored as an episode.
2. Referential rendering. The faithful renderer refers to prototypes by relations the entity's own history defines (the same as a moment ago, seen often, not seen before, seen together with what is heard now, its learned name if one exists), in place of the magnitude tables for perceptual content. Magnitude words stay for interoception and affect, where the quantity is the content.
3. Word-referent association. When speech-to-text is on, an online cross-situational learner strengthens associations between heard word types and the prototypes active at the time. Only association weights and, subject to an operator ruling, the word types of a learned lexicon persist; no transcript, order or utterance is kept.
4. The shared referent space. When `latent-workspace-content-level` provides its accessed content code, prototypes and word associations form over that code, so one referent can be seen and heard. That change owns the code; this change only consumes it through its declared interface and falls back to per-sense prototypes when it is off.
5. Voice alignment's chosen-text source stays with `voice-development`; this change adds no training of the organ.

## Capabilities

### New Capabilities

- `perceptual-prototypes`: online, label-free prototype formation in the perceptual modules, its report fields and its persistence rule.
- `word-referent-association`: the cross-situational learner, what it persists, and how a learned name reaches the renderer.

### Modified Capabilities

- `faithful-renderer`: referential rendering of perceptual content.

## Impact

- Code: `kaine/modules/vision/`, `kaine/modules/audition/` (prototype layer), a shared `kaine/modules/prototypes.py`, `kaine/faithful/felt.py` and `templates.py`, a new learner beside the audition module's transcription path, state persistence and fork/merge for prototypes and associations, `kaine/privacy_filter.py` (new vector fields stripped).
- Workspace: report payloads gain prototype fields; no new candidate type.
- Studies: none until after the module-addition study; then an offline validation and one supervised validation boot.
- Docs: `docs/09-modules/vision.md`, `audition.md`, `language.md`; a paper revision note for §3.5 and §9.
