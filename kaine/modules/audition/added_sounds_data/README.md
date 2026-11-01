# Added sounds

These files are the recurring melody and the outside voice of the developmental stimulus (paper §7 and A.7; [the developmental phase](../../../../docs/06-operation/development.md)). The stimulus-source audio plays them in slots without maternal speech; it never synthesizes sound at runtime.

- `melody.toml`: the note list, written for KAINE. "Twinkle, Twinkle, Little Star" in G major from G4, the melody Partanen et al. (2013) had mothers play in the last trimester; every fundamental lies between 392 and 659 Hz, inside the stage-0 hearing band. The tune is traditional and in the public domain.
- `melody.b0.flac`, `melody.b1.flac`, `melody.b2.flac`: the melody at 0.50, 0.55 and 0.60 s a beat (24.0, 26.4 and 28.8 s).
- `texts.toml`: the outside voice's ten texts, original to KAINE, everyday and neutral, with no names; each is two or three short lines.
- `x*.flac`: the outside voice, two takes of each text, 3.4 to 5.7 s each, 87.7 s in all, at 2.2 to 2.9 words a second with the pauses.
- `manifest.json`: every file's sha256 and frame count, the generator settings and, for the outside voice, the seed of each take and the reference-voice attribution. The runtime refuses to start the stimulus audio if any file is missing or differs from it.

All files are 8 kHz, mono, 16-bit FLAC, normalized to -20 dBFS RMS with peaks at most -1 dBFS; about 1.6 MB in all.

## How they were made

`tools/maintainer/render_melody.py` renders the melody from `melody.toml`: each note a harmonic tone (eight partials with amplitude 1/k) under a smooth envelope (20 ms raised-cosine attack, gentle decay, 60 ms release, 40 ms between notes). It draws no random numbers, so rendering again reproduces the files.

`tools/maintainer/generate_outside_voice.py` rendered every outside-voice take with Chatterbox TTS 0.1.6 (Resemble AI, MIT licence), model `ResembleAI/chatterbox` at revision `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`, the maternal voice's version, revision and settings (exaggeration 0.5, CFG weight 0.5, temperature 0.8), base seed 20261031, on the CPU. Rendering again with the same versions, seeds and device reproduces the takes; bit-exact output also needs the same hardware and library stack, so `--verify` checks the shipped files against the manifest.

The voice is conditioned on seven utterances of the CMU ARCTIC speaker `rms`, a male US English speaker recorded at Carnegie Mellon University for building speech-synthesis voices (Kominek and Black 2003, http://www.festvox.org/cmu_arctic/). Of the database's male speakers he has the lowest fundamental, so the takes' median fundamentals (82 to 132 Hz) lie below stage 1's lower edge (about 158 Hz) and arrive with the 100 Hz step. The database is free for any use provided its notice is kept; the notice is reproduced in `THIRD_PARTY_LICENSES.md`. The rendering is a synthetic voice; it is no recording of that speaker or of any other person.

Every outside-voice take carries Chatterbox's Perth implicit watermark (`perth.PerthImplicitWatermarker.get_watermark` reads 1.0 on each take and 0.0 on noise). A Whisper transcription of each take matched its text. The generator renders each line separately, with a seed per line, and joins the lines with seeded pauses of 0.6 to 1.0 s: the model speaks a whole sentence at about 4.4 words a second whatever its exaggeration, CFG weight or reference pace, which is fast for someone talking in a room.
