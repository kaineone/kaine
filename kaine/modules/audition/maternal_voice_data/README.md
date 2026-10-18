# Maternal-voice repertoire

These files are the maternal voice of the developmental stimulus (paper §7 and A.7; [the developmental phase](../../../../docs/06-operation/development.md)). The stimulus-source audio plays them; it never synthesizes speech at runtime.

- `texts.toml`: the original texts, written for KAINE, in unlock order. The first item is the repeated passage.
- `*.flac`: one file per take, 8 kHz, mono, 16-bit FLAC, trimmed and normalized to -20 dBFS RMS. 41 takes of 20 items, about 200 s and 2.1 MB in all.
- `manifest.json`: every take's sha256, frame count and seed, the generator settings and the reference-voice attribution. The runtime refuses to start the stimulus audio if any file is missing or differs from it.

## How they were made

`tools/maintainer/generate_maternal_voice.py` rendered every take with Chatterbox TTS 0.1.6 (Resemble AI, MIT licence), model `ResembleAI/chatterbox` at revision `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`, base seed 20261018, exaggeration 0.5, CFG weight 0.5 and temperature 0.8, on a CUDA GPU. Rendering again with the same versions and seeds reproduces the takes; bit-exact output also needs the same GPU and driver stack, so `--verify` checks the shipped files against the manifest.

The voice is conditioned on seven utterances of the CMU ARCTIC speaker `slt`, a female US English speaker recorded at Carnegie Mellon University for building speech-synthesis voices (Kominek and Black 2003, http://www.festvox.org/cmu_arctic/). The database is free for any use provided its notice is kept; the notice is reproduced in `THIRD_PARTY_LICENSES.md`. The rendering is a synthetic voice; it is no recording of that speaker or of any other person.

Chatterbox embeds its Perth implicit watermark in every output. It survives the resampling to 8 kHz and the stimulus's 500 Hz low-pass (checked with `perth.PerthImplicitWatermarker.get_watermark`, which reads 1.0 on these files and 0.0 on noise).
