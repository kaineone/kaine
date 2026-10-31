## Why

The paper's §4 table now describes the social cognition module honestly: "per-channel tone-of-voice models with familiarity and a social prediction error for departures from a channel's emotional pattern; no attribution of mental states", under the brain function "mentalizing" (Premack and Woodruff 1978, the construct; Frith and Frith 2006). The gap between that row's two columns is the subject of this change.

What the module is today (`docs/09-modules/social-cognition.md`; `kaine/modules/social_cognition/`):

- Agent identity is the audio channel. Every operator-facing channel maps to one agent named by `speaker_label`, and any other channel becomes `media:<channel>` (`kaine/modules/social_cognition/module.py:187-190`). Two people on one microphone are one agent; every voice in a film is one agent.
- An agent is a histogram of eight vocal-emotion categories with an interaction count and a reliability (`agent.py:1-40`). The social error is the histogram's deviation from the observed category.
- `_handle_transcription()` ignores the text, and `on_workspace()` does nothing.
- The social drive is met by any interaction the sequence module times (`kaine/modules/affect/module.py:1509-1518`; paper §3.5, "Each heard voice meets the social drive"), whoever speaks and whatever they do.

Mentalizing is the attribution of mental states such as goals, beliefs and attention to others. Computational accounts treat it as inference: an observer explains another agent's behaviour by the hidden states that would produce it (Baker, Saxe and Tenenbaum 2009), and predictive accounts frame theory of mind as predicting others' behaviour and learning from the errors (Koster-Hale and Saxe 2013, to verify). A histogram of expressed emotion per channel predicts nothing about an agent's behaviour and infers no hidden state. The audit flagged this as E11; the triage put it in W5 as "speaker individuation by embedding clustering and a predictive agent model (M then L)".

## What Changes

A staged design. Each stage is validated offline before any entity uses it.

1. Speaker individuation. A local speaker-embedding model turns each voiced segment into a voice embedding, and an online clustering step (the prototype layer of `language-grounding`) forms one agent per voice, across channels. The entity's own voice is excluded through the vocal module's speaking gate. The channel stays as context, not identity. Only voice centroids persist, encrypted, and the operator rules on keeping a voice centroid of a real person.
2. A predictive agent model. For each agent, a small model predicts the agent's next turn from context: whether and how soon it speaks after the entity speaks, its expressed vocal affect, and its turn length. Its prediction errors are published as precision-scaled reports like every other processor's, replacing the histogram deviation.
3. A first attributed state. Each agent model carries a latent "engaged with me" state inferred from how contingently the agent responds to the entity's own utterances, the simplest mental state an audio-only observer can attribute, with a cited developmental basis. It is published as an agent fact and can join the competition.
4. Goal and belief attribution by inverse planning needs agents that act in a shared world. It is out of scope here and named as the follow-up once embodiment and a content-bearing world model exist.
5. The social drive's relief is unchanged by this change; whether contingent engagement should meet it instead of any heard voice is an open decision with welfare weight, left to the operator after stage 3's offline results.

## Capabilities

### New Capabilities

- `speaker-individuation`: voice embeddings, agent formation across channels, self-voice exclusion, and what persists.

### Modified Capabilities

- `social-cognition`: agents are voices, not channels; the predictive agent model and its reports; the engagement state.

## Impact

- Code: `kaine/modules/social_cognition/` (agent identity, agent model, reports), `kaine/modules/audition/` (voiced-segment embedding through the speech backend), `kaine/speech_manifest.py` and provisioning for one speaker-embedding model, the shared prototype layer from `language-grounding`, the privacy filter.
- Workspace: the social error report changes its meaning and intensity; the engagement fact is a new candidate type.
- Setup: one additional local model download, consented, with its license recorded.
- Studies: none until after the module-addition study, in which this module is the fifth added.
- Docs: `docs/09-modules/social-cognition.md`; a paper revision note for the §4 row.
