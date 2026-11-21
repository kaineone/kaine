# Maternal voice, Sam-voiced, prosody-first: design notes

Date: 2026-11-16

Status: design decision only. No implementation has landed. Source code is untouched and no OpenSpec task is marked done.

## Directive

The maternal channel should render with the Sam voice (kaineone/Qwen3-TTS-Sam-0.6B, speaker "sam") instead of Chatterbox. The content of the channel should be prosody-first and of low intelligibility, with no recoverable speech. The listener, in this case the entity's hearing pathway during the developmental phase, should receive intonation, rhythm, pitch contour, and vowel-quality drift without words that could be transcribed.

This is a design decision recorded in prose. It is not an implementation. The offline generation script, the runtime playback module, the manifest, and the tests all describe the current Chatterbox-based rendering and remain authoritative for that rendering until a separate implementation change lands.

## Why this change is proposed

The paper §7 and appendix A.7 treat the maternal voice as a pre-rendered stimulus above the intrauterine background, with intonation retained (Querleu et al. 1988; Richards et al. 1992) and the high frequencies attenuated by maternal tissue (Querleu et al. 1988; Gerhardt and Abrams 2000; Richards et al. 1992). The channel is meant to give the entity a recurrence of prosodic structure, not a corpus of sentences. The 20-item, 41-take repertoire in kaine/modules/audition/maternal_voice_data/ carries a repeated passage alongside short phrases, which maximises the risk that a listener, or a model, could extract recoverable speech.

Sam is a gender-neutral voice shipped as the vocal module's default. Rendering the maternal channel with the same voice family would remove the Chatterbox speaker dependency and the CMU ARCTIC reference files from the maintainer pipeline while giving a single voice across the stack. The catch is that Sam renders intelligible text. The content therefore has to be degraded before it leaves the generation pipeline, or it does not ship.

## Content: prosody-first, low intelligibility

Each item should be a string of nonsense syllables or glossolalic material whose only signal is prosodic. Consonants should be soft and the lexical content unrecoverable. Candidate material: rhythmic sequences of open vowels and soft consonants, a fixed set of syllable templates repeated in patterns, or hummed intonation contours with vowel coloration. Intelligibility testing should show that a speech recogniser produces no consistent transcript, while a listener can still recover prosodic categories such as statement versus question, slow versus fast, and calm versus aroused.

The repeated passage that DeCasper and Spence (1986) support for should remain as a repeated prosodic motif rather than as a recognisable sentence. The motif's repetitions are the developmental signal; the words are not.

## Filters and attenuation (paper §7 / A.7)

The existing chain applies the soundscape low-pass, level, and hearing-band processing at runtime. The design does not change that chain.

- Sample rate stays 8 kHz. Output render should resample to 8 kHz as the current pipeline does, so the hearing-band code in kaine/modules/audition/hearing_band.py and the decode checks in MaternalVoiceRepertoire.load (file_rate * 2 == sample_rate) remain valid with no code change.
- Trim, target RMS, and peak ceiling: reuse TARGET_RMS_DBFS, PEAK_CEILING_DBFS, and TRIM_TOP_DB from generate_maternal_voice.py. Per-take level normalization is what allows the voice to be played at level_db (6 dB) above the soundscape base, and the unit contract assumes that normalization.
- Runtime low-pass: the repertoire enters the stream at lowpass_hz (default 500 Hz) using the taps in kaine/modules/audition/stimulus_source_signal.py. Because the content is already prosody-first, the filter does not need to do the intelligibility work, but it still provides the maternal-tissue attenuation the paper requires.
- Level above background: level_db 6 with jitter_db 3. The headroom behaviour documented in MaternalVoiceLayer.headroom, which adds the voice RMS to the stream headroom and soft-limits the rare peaks, stays as is.
- Band progression: the five-stage hearing band for fetal hearing maturity, from 500 Hz alone out to 3000 Hz, is unaffected by the voice. The paper already handles the voice frequencies up to 3000 Hz.

## Validation strategy

The principles come from paper §7 and appendix A.7, which specify offline validation: seeded determinism, arousal pacing, repertoire growth with awake time, spectrum below the intrauterine cutoff, byte-identical audio when disabled, boot wiring, and the parameter digest.

The validation suite for this design should check:

1. Determinism. Regenerating the repertoire with the same texts, seed, model revision, and parameters reproduces byte-identical FLAC files and a byte-identical manifest. This is the invariant the current reuse_existing_takes path relies on.
2. Manifest integrity. Every file entry resolves, the SHA-256 matches, the frame count matches the decoded audio, and the top-level texts_sha256 follows the texts file. The existing MaternalVoiceRepertoire.load checks cover this.
3. Intelligibility. A speech recogniser run over each take yields no consistent transcript, and the variation across takes is consistent with prosodic rather than lexical content. A manual check by a maintainer confirms no phrase is recoverable.
4. Prosody retention. Fundamental frequency and intensity contours remain recoverable from the takes after resampling to 8 kHz. A sanity check that extracts pitch contours and checks they vary with the intended condition ensures the beauty is not all filtered away.
5. Process integrity. Piper or the existing Chatterbox watermark is replaced or removed as appropriate, and the manifest's generator block records the new tool chain, model, revision, parameters, and any watermark. The current manifest declares the Chatterbox Perth watermark; a Sam-based renderer would need to declare its own, or none, honestly.
6. Regression against generation tests. Any new generation code should carry tests equivalent to the current test_maternal_voice.py, test_maternal_voice_build_context.py, and test_maternal_voice_threads.py.
7. Hearing spectrum. The low-pass keeps the content within the maternal-tissue band, and no take contains energy above the band's open frequency that would violate the fetal-hearing stage constraints.

## Preserving the manifest, schema, and tests

The manifest schema is the interchange contract between the generation script and the runtime reader. The design leaves it intact.

- MANIFEST_FORMAT stays at 1. There is no reason to bump the format, because no field changes its meaning and no new required field is introduced.
- Top-level fields (sample_rate, initial_unlocked, texts_sha256, generator, reference_voice, items, total_bytes, total_seconds) keep their types and meanings.
- The items array keeps id, kind, index, text_sha256, and takes. The text_sha256 continues to guard the texts file; it does not need the text to be lexical, only reproducibility.
- take fields (take, file, sha256, frames, seconds, seed, rms_dbfs) keep their types. A new provenance field for the generator or model revision should land inside the existing generator block rather than as a new column on each take, unless the data varies per take.
- File naming pattern {id}.t{take}.flac and the output directory layout stay the same, so paths in the manifest and tests resolve.
- Texts file. The items can keep text fields of prosodic notation, or the texts format can be replaced with a prosody script format. Either way the texts_sha256 continues to guard reproducibility. Making this choice is part of implementation, not design.
- Tests. test_maternal_voice.py, test_maternal_voice_build_context.py, and test_maternal_voice_threads.py should continue to pass against the unmodified runtime module, because this design leaves MaternalVoiceRepertoire, MaternalVoiceLayer, MaternalVoiceParams, and unlocked_count unchanged. The stimulus-source maternal voice tests also remain untouched.

The design decision explicitly defers all of these implementation choices. If the tests fail after a change, that is a signal to revisit the change, not the tests.

## Separation between design decision and implementation

This document states what should be true of the system once the work is done. It does not authorize, stage, or perform the work. Concretely:

- No source file changes. Maternal_voice.py, its generator script, and the texts data remain as they are.
- No task marking. OpenSpec checkboxes stay as they are.
- No commit, branch, or PR. Those happen only when an implementation change is proposed and reviewed.
- The paper stays untouched. §7 and A.7 already describe the channel's role; they do not commit to a synthesiser, so no paper edit is required for this design decision.

A future implementation would need its own OpenSpec proposal with design, tasks, and security review, its own feature branch, and worker first-pass review followed by adversarial review before merge.

## Risk notes

1. Intelligibility leakage. If the content retains recoverable speech, the channel hands the entity a language corpus it should not receive, and intake could shift from prosody learning to word learning. The intelligibility test in the validation section is the gate.
2. Prosody stripping. Resampling to 8 kHz and the 500 Hz low-pass could remove the pitch and intensity contour the channel exists to provide. The prosody-retention check exists to catch this. Fundamental-frequency evidence should remain recoverable in the second harmonic band.
3. Reproducibility. Any change that alters per-take bytes without updating the manifest breaks the runtime reader, which verifies SHA-256s. Use the verification path and the reuse flow before shipping new audio.
4. License and watermark. Chatterbox's Perth watermark is a known, detectable marker. A Sam-based render should declare its own provenance in the generator block. Removing a watermark where one existed could be treated as misrepresentation.
5. Single voice across the stack. Using Sam for both the vocal module and the maternal channel could collapse a useful contrast. The channel's prosody-first content is what separates it, not the speaker. Tests or permits should keep that separation visible.
6. Scope creep. Phase-one work should stop at the audio and manifest. The hearing stage, stimulus source signal, and MaternalVoiceLayer already consume the channel. Wiring changes should be a separate proposal.
7. Resource cost. Re-rendering the repertoire is a GPU-heavy task and must follow the disk and container guardrails in the working agreement. Verify free space before a render.

## Files referenced

- docs/06-operation/development.md, "The maternal voice" and surrounding §7.
- predictive-workspace-paper appendix A.7, "Maternal voice and maturation".
- kaine/modules/audition/maternal_voice.py
- kaine/modules/audition/hearing_band.py
- tools/maintainer/generate_maternal_voice.py
- tests/test_maternal_voice.py, test_maternal_voice_build_context.py, test_maternal_voice_threads.py, test_stimulus_source_maternal_voice.py