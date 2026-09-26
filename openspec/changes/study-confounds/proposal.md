# Proposal — `study-confounds`

## Why

Watching films exposes three places where the entity is told something false about what it hears, or can act where it physically could not:

- **Film voices are modelled as the operator.** Every `audition.emotion` and `audition.transcription` is attributed to the single configured `[empatheia].speaker_label` (`"operator"`), whatever the source. Playlist audio reaches Audition through the live-microphone path with `source_label = "live_mic"`, the same label a real microphone has. So a film's dialogue shapes the entity's model of its operator: their emotions, their familiarity, their "social errors".
- **Film dialogue counts as speech addressed to the entity.** Volition treats every `audition.transcription` as a user utterance and forms a `speak` intent to answer it. With transcription on, the entity would try to reply to the characters in a film as though they were talking to it.
- **Vox can speak in the womb.** During gestation Mundus is held dormant, because there is no world to act in. Vox is not, although there is no air to speak into. With Vox enabled in gestation, spoken output would reach the room.

The first two are false facts that the architecture tells the entity, not behaviour that emerged. The third is an effector acting where no medium exists. All three also confound the module-ignition study: Empatheia's and Volition's contributions to the workspace would reflect the mislabelling rather than the faculties.

## What changes

- **Audio carries its channel.** The live-microphone path is given a `source_label` for the feed it plays: `playlist`, `seeded`, `womb`, `screen`, and `live_mic` for a real microphone. Remote audio keeps `remote`.
- **Empatheia attributes by channel.** Audio from an operator channel (`[empatheia].operator_sources`, default `live_mic`, `microphone`, `remote`) is attributed to `speaker_label`, as today. Audio from any other channel is attributed to one agent per channel, `media:<channel>`, for example `media:playlist`. It is not diarized per character, because nothing here can tell voices apart. It is modelled honestly as "others heard through that channel".
- **Volition answers only speech from an operator channel.** A transcription is a user utterance only when its `source_label` is an operator source. Other speech is still perceived and can still win the workspace; it is just not treated as addressed to the entity.
- **Vox is dormant in the womb.** Like Mundus, Vox is held dormant while gestating and activated at birth. Lingua keeps running: inner speech is not held.

## Impact

- `kaine/boot.py` (the source label per feed), `kaine/modules/empatheia/module.py`, `kaine/workspace/volition.py`, `kaine/modules/vox/module.py` (`set_dormant`), `kaine/cycle/__main__.py` and `kaine/lifecycle/gate_runner.py` (Vox dormant in gestation, activated at birth), `config/kaine.toml` (`operator_sources`).
- With a live microphone, behaviour is unchanged.
