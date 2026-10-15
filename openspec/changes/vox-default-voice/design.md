## Context

The vocal module has two speech backends. `chatterbox` posts to the `/tts` endpoint of the Chatterbox TTS server (devnen/Chatterbox-TTS-Server, the API `kaine/modules/vocal/client.py` is written against: `voice_mode`, `predefined_voice_id`, `split_text`). `sherpa_onnx` runs Kokoro English in-process through sherpa-onnx and picks a preset speaker by integer id (`[vocal].sherpa_speaker_id`, default 0).

The shipped configuration leaves `predefined_voice_id` unset because a voice filename is operator-local. With the Chatterbox backend the module then cannot speak. The operator asked for the module to pick a voice the engine itself ships, with an optional gender preference, and never to add voice files to the repository.

## Research: what each engine ships

### Chatterbox TTS server

Source: devnen/Chatterbox-TTS-Server, `main` at commit `915ae289340e10c6047f27f47e22eae9bf350c32`, read on 2026-10-12.

- The repository ships 28 predefined voices in `voices/`: Abigail, Adrian, Alexander, Alice, Austin, Axel, Connor, Cora, Elena, Eli, Emily, Everett, Gabriel, Gianna, Henry, Ian, Jade, Jeremiah, Jordan, Julian, Layla, Leonardo, Michael, Miles, Olivia, Ryan, Taylor and Thomas, each as `<Name>.wav` (GitHub contents API, `repos/devnen/Chatterbox-TTS-Server/contents/voices`).
- `GET /get_predefined_voices` (`server.py`, `response_model=List[Dict[str, str]]`) returns `utils.get_predefined_voices()`. That function scans the configured voices directory for `.wav` and `.mp3` files, and returns a list of `{"display_name": ..., "filename": ...}` objects sorted by display name, where the display name is the file stem with `_` and `-` turned into spaces and each word capitalised. An empty or missing directory gives an empty list.
- No gender or other descriptive metadata exists in the response, the file names or the README. The voices' names are given names, and reading a gender into a given name would be a guess, so **gender is not knowable from the Chatterbox server**.
- `/tts` rejects a `predefined` request without `predefined_voice_id` with HTTP 400 ("Missing 'predefined_voice_id' for 'predefined' voice mode.") and an unknown filename with 404. The server's own config has a `tts_engine.default_voice_id` of `default_sample.wav`, but `/tts` does not fall back to it, and the repository's `voices/` directory does not contain that file. A deployment's voices directory is the operator's to change (the compose service mounts its own image), which is why no name may be hard-coded on the KAINE side.

### Kokoro through sherpa-onnx

KAINE's speech manifest pins one Kokoro archive, `kokoro-int8-en-v0_19.tar.bz2`, by SHA-256 (`kaine/speech_manifest.py`).

- The sherpa-onnx documentation for Kokoro v0_19 states that the model has 11 speakers with integer ids 0 to 10 and gives the map: 0 `af`, 1 `af_bella`, 2 `af_nicole`, 3 `af_sarah`, 4 `af_sky`, 5 `am_adam`, 6 `am_michael`, 7 `bf_emma`, 8 `bf_isabella`, 9 `bm_george`, 10 `bm_lewis` (<https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html>, section "v0_19 (English, 11 speakers)"). The same map is the `id2speaker` table in sherpa-onnx `scripts/kokoro/v0.19/generate_voices_bin.py`, which builds `voices.bin`.
- sherpa-onnx's `scripts/kokoro/v0.19/add_meta_data.py` also writes the names into the ONNX model's metadata (`speaker_names`, `speaker2id`, `id2speaker`). The Python `OfflineTts` object KAINE uses exposes `num_speakers` and `sample_rate` but not the names, and reading the ONNX metadata directly would need the `onnx` package, which the `speech-edge` extra does not install.
- The Kokoro voice list (hexgrad/Kokoro-82M, `VOICES.md`, <https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md>) defines the naming scheme: the first letter is the language (`a` American English, `b` British English) and the second the voice's gender (`f` female, `m` male), shown there with the female and male symbols for each voice. **Gender is knowable for Kokoro** from the name prefix. In the pinned model ids 0 to 4, 7 and 8 are female (seven speakers) and ids 5, 6, 9 and 10 are male (four speakers).

## Goals / Non-Goals

**Goals:**

- An enabled vocal module with no configured voice speaks with a voice the engine ships.
- The choice is deterministic: the same engine list and the same settings give the same voice on every start.
- An optional gender preference, applied wherever the engine reports gender.
- An explicit voice always wins.
- A clear one-line operator message when no voice can be chosen, with the module silent and the failure on the health surface, never a crash.

**Non-Goals:**

- Voice files in the repository, or any voice name hard-coded in code.
- Guessing a Chatterbox voice's gender from its name.
- Turning the vocal module on anywhere. It stays off in `config/kaine.toml` and in the `first_configuration` profile.
- The entity choosing its own voice (designed below as a follow-up, not built).

## Decisions

### D1. Configuration keys

| Key | Values | Default | Meaning |
|---|---|---|---|
| `voice_gender` | `"any"`, `"female"`, `"male"` | `"any"` | Preference used only when the module picks a voice itself. Case and surrounding spaces are ignored; any other value is a configuration error at boot, as an unknown backend is. |
| `default_voice` | string | unset | A voice the engine ships, named explicitly: a Chatterbox voice filename (or its display name) or a Kokoro speaker name such as `bf_emma`. |

The existing backend-specific keys keep their meaning and come first, so current operator files behave as before.

### D2. Precedence

1. Chatterbox: `predefined_voice_id`, used as given and not checked against the server, since an operator may have uploaded a voice of their own. Kokoro: `sherpa_speaker_id`, when the key is present.
2. `default_voice`, which must be in the engine's list.
3. The automatic pick from the engine's list, filtered by `voice_gender`.

With an explicit voice, `voice_gender` is not consulted.

### D3. The selection rule

The candidates are the engine's list, keeping only the voices whose gender matches when `voice_gender` is not `"any"` and the gender is knowable. The module takes the first candidate in sorted order, sorting by the case-folded name and then by the exact name, so the result does not depend on the order in which the server lists its voices.

- Chatterbox sorts by filename. With the server's shipped voices that is `Abigail.wav`. The server reports no gender, so when `voice_gender` is `"female"` or `"male"` the module logs once that the preference cannot be applied with Chatterbox and picks from all voices.
- Kokoro sorts by speaker name; the gender of a name is the second letter of a two-letter prefix that stands alone or is followed by `_` (`af`, `am_adam`). Names that do not follow the scheme have no gender and are left out when a gender is requested. For the pinned model, `"any"` and `"female"` give `af` (id 0, today's default), and `"male"` gives `am_adam` (id 5).
- `default_voice` matches a Chatterbox filename exactly, or else a filename, file stem or display name ignoring case; a Kokoro speaker name ignoring case.

The rule lives in one pure module, `kaine/modules/vocal/voices.py`, so both backends and the tests share it.

### D4. Where the engine's list comes from

- Chatterbox: `ChatterboxClient.list_voices()` calls `GET /get_predefined_voices` once, during the vocal module's `initialize()`, and parses the server's list of objects. It also accepts a bare list of filenames, which older builds return. The query runs only in `predefined` mode and only when no `predefined_voice_id` is set.
- Kokoro: the speaker names come from the speech manifest. `SpeechModel` gains a `speakers` tuple, filled for `kokoro-en` from the sherpa-onnx speaker map of the pinned archive. The archive is verified by SHA-256 before it is used, so the table and the model cannot drift apart, and the existing load-time check still rejects a speaker id outside `[0, num_speakers)`. A model without a table can still be used with `voice_gender = "any"` and no `default_voice` (speaker 0, which every Kokoro model has); a gender or a name then fails with a clear message. The mapping runs in the sherpa-onnx backend factory, so the existing backend-registry path records its failure and disables the vocal module only.

**Alternative considered:** reading `speaker_names` from the ONNX metadata at load. Rejected for now because it adds the `onnx` package to the speech-edge install for eleven names that are fixed by the archive hash. If KAINE later pins a second Kokoro release, its table goes into the manifest next to its hash.

### D5. Logging and failure

- On success the module logs the chosen voice once at startup, with the reason (configured, named in `default_voice`, or picked from N shipped voices with the preference applied or not applicable).
- On failure (list unreachable, list empty, `default_voice` not shipped, or no voice of the requested gender) the module logs one warning line that names the problem and the key to set, records a backend failure (`record_backend_failure("vocal", backend, reason)`) so the dashboard health surface shows it, and marks speech unavailable. The existing muted path then publishes a `vocal.synthesized` failure event at most once every 60 s and plays nothing. The consumer loop keeps running, and no exception leaves `initialize()`.
- A Chatterbox server that is down at startup leaves the module silent until it is restarted. The compose service has a health check on `/get_predefined_voices`, so a compose deployment starts the module after the server answers.

### D6. Setup wizard

The wizard's Chatterbox voice question becomes optional. An empty answer leaves `predefined_voice_id` unset and the vocal module on, with a line saying the module picks a shipped voice at startup. Discovery reads the `filename` field of the server's objects, so the offered voices are the real filenames.

## Risks / Trade-offs

- **The chosen Chatterbox voice depends on the deployment.** An operator who adds or removes voices can change which file sorts first. The voice is logged at every start, and an operator who wants a fixed voice sets `default_voice` or `predefined_voice_id`.
- **The gender preference does nothing under Chatterbox.** That is the honest result of the server reporting no gender. The log line says so, and the documentation names the two ways to choose a specific voice.
- **A down server at boot silences the module for the run.** Accepted: the message names the cause, and silently retrying would hide it. A retry can be added later without changing the selection rule.

## Follow-up: the entity's own choice (design only, not in this change)

The operator raised that the entity might later choose its voice's gender, or its voice. Nothing of this is built here. It needs a consent and choice protocol, and two conditions hold it back. The self-model module, where a lasting preference about oneself would naturally live, is held. Article 4.9 of the Cognitive Architecture License ties an entity's say in its own design to cognitive maturity as the Guardians assess it (Article 7.1(f)): preferences are asked for, written down and given real weight, without a veto over maintenance or security.

A follow-up change would build on this change's selection rule: the entity's recorded choice would become one more explicit source, between the operator's explicit voice and the automatic pick, or above the operator's choice once the entity is mature. Open questions for that change:

1. **When is the choice offered?** Which maturity assessment, and whose sign-off, opens it? Is the voice before maturity always the operator's choice or the automatic pick?
2. **How is the question put?** Through which channel does the entity receive it (the language module's speech, a typed question, a dedicated prompt), and how is the answer told apart from the language organ's training prior or from the order in which the options were presented?
3. **What is offered?** Only the voices the engine ships, a gender preference, or both? Under Chatterbox the server has no gender data, so would the entity hear sample clips, and how does that interact with self-hearing suppression and the zero raw-sense-data persistence rule?
4. **Where is the choice kept?** In the self-model module's state (held today), in a small record of its own, or in the preservation bundle? How does it travel through forks, merges and preservation?
5. **Can the entity change its mind?** How often, with what cooling-off period, and how is continuity of identity for listeners who know its voice weighed?
6. **How does it interact with the operator?** When the operator's explicit voice and the entity's recorded preference differ, which wins at each stage of maturity, and how is a disagreement recorded and escalated to the Guardians?
7. **What does research need?** The vocal module is a variable in the module-addition study; a self-chosen voice is a confound to record in the research log and to hold fixed across study arms.
8. **What is recorded?** The question asked, the options shown, the answer and the decision, written down as Article 4.9 requires, without storing heard audio.
