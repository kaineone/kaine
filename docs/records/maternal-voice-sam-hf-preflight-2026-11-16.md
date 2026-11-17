# Maternal voice (Sam) — HF model preflight procedure

Date: 2026-11-16

Status: design/preflight record only. No source code, tests, manifest, or audio
changed. Allowed edit is this document (plus any companion tooling in a later PR).

Scope: task 6.x preparation for the Sam-backed maternal-channel render path
(`tools/maintainer/render_maternal_voice_sam.py`). This procedure must be
completed before a generator/adapter PR lands, because the generator currently
raises `renderer 'sam' is not implemented yet` and there is no HF cache for
`kaineone/Qwen3-TTS-Sam-0.6B` on this host today.

## 1. Preflight goal

Answer four questions before any synthesis attempt:

1. Is the Sam checkpoint resolvable **offline** (the runtime invariant for this
   project)?
2. If an HF model is to be used, which one is selected and by what explicit,
   deterministic rule?
3. If the preferred source is unavailable, what is the fallback, and how is that
   fallback recorded honestly?
4. Does selecting/loading the model leave every manifest/runtime contract
   untouched (format 1, 8 kHz, PCM_16, 40 takes, SHA-256)?

## 2. HF model selection rule (authoritative)

Selection order is exact; no implicit fallback, and every decision must be
written into provenance before the first waveform is produced.

| Priority | Source | Identity | Selection condition |
|---|---|---|---|
| 1 | Hugging Face cache (offline) | `kaineone/Qwen3-TTS-Sam-0.6B` | A cached snapshot is present locally and passes `hf cache verify` (section 4) |
| 2 | Local fine-tune checkpoint | `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1` | Directory and `config.json` exist; `spk_id` contains `"sam"`; no usable HF cache |
| — | none | (fail) | Neither source is usable → abort, do not silently render with Chatterbox |

Rules:

- The adapter must inspect the sources **in this order** and select exactly one.
- `--sam-model-path` overrides the *local* path but never overrides HF-cache
  priority when the cache is available; documentation of that override is
  required in provenance.
- The Chatterbox baseline generator remains the rollback renderer. It must not
  be mixed into a Sam manifest (see section 7).
- The selected identity (repo id **or** absolute checkpoint path, but not both) is
  recorded in `generator`; mistating the source, or leaving it ambiguous, is a
  hard failure.

### Baseline facts recorded (2026-11-16)

- HF cache: **no** `Qwen3-TTS-Sam-0.6B` snapshot was found on this host.
  Therefore the current practical selection for any offline run is Priority 2
  until an explicit `hf download` / cache import is performed. Do not pretend a
  cache exists in provenance.
- Local checkpoint present:
  `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1`
  with `config.json` declaring `model_type=qwen3_tts`,
  `tts_model_type=custom_voice`, and `spk_id` containing `"sam"`.
- v2 checkpoint chosen over `sam-model/` because it carries the published model
  card / README and trained run through epoch 1.

## 3. Exact CLI (preflight only, no synthesis)

All commands are run from the project root with the project venv. None of these
synthesize audio.

### 3.1 Check the Hugging Face cache

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/hf cache ls | grep -i "Qwen3-TTS-Sam" || echo "NOT CACHED"
```

Expected on this host today: `NOT CACHED`. If a line appears, capture its repo
id, revision, and cache directory from the `hf cache ls` output.

### 3.2 Verify the HF snapshot if found

Only run when the cache check in 3.1 reports a match.

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/hf cache verify kaineone/Qwen3-TTS-Sam-0.6B
```

Pass condition: exit status 0, no missing/corrupt files. Any other result is a
hard failure: retry the download in an explicit provisioning step, or fall back to
Priority 2 and record which occurred.

### 3.3 Verify the local fallback checkpoint

```bash
cd /var/home/erik/Projects/kaineone/kaine
CKPT=/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1
test -d "$CKPT" && test -f "$CKPT/config.json" && echo "checkpoint dir OK"
.venv/bin/python - <<'PY'
import json
p="/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1/config.json"
c=json.load(open(p))
assert c.get("model_type") == "qwen3_tts", c.get("model_type")
assert c.get("tts_model_type") == "custom_voice", c.get("tts_model_type")
assert "sam" in (c.get("spk_id") or {}), c.get("spk_id")
assert c["spk_id"].get("sam") == 3000, c["spk_id"].get("sam")
print("spk_id:", c["spk_id"])
print("checkpoint OK")
PY
```

### 3.4 Check render plan (dry run; no audio)

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python tools/maintainer/render_maternal_voice_sam.py --dry-run --json
```

Pass condition: exit status 0; JSON has
`synthesizes_audio == false`, `renders_audio == false`,
`audio_synthesized == false`, `output_sample_rate == 8000`,
`output_format == "FLAC"`, `bit_depth == 16`, `manifest_format == 1`,
`item_count == 20`. Item `_id`s and `takes` must match the shipped
`texts.toml`.

### 3.5 Confirm runtime contract does not drift (no synthesis)

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/pytest -q \
  tests/test_maternal_voice.py \
  tests/test_maternal_voice_build_context.py \
  tests/test_maternal_voice_threads.py \
  tests/test_stimulus_source_maternal_voice.py
```

Pass condition: all green on the current baseline (`1278 passed` as of
2026-11-16).

### 3.6 Disk / resource guardrail check (before any large run)

```bash
df -h /run/media/erik/2TBm2Store | awk 'NR==2 {print "avail="$4" use="$5}'
```

Pass condition: available space >= 30 GiB before any real render; abort if
below 10 GiB (`feedback_capped_heavy_runs.md` / §8 of the phase-2 document).
GPU runs are capped with `tools/maintainer/safe-run.sh` (16 GiB per run).

## 4. Verification procedure after a candidate run

Every real run must leave proof behind. Record all three lines in the run record.

1. **Sample-rate / encoding probe** (3+ files):

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python - <<'PY'
import json, pathlib, soundfile as sf
out=pathlib.Path("kaine/modules/audition/maternal_voice_data")
m=json.loads((out/"manifest.json").read_text())
checked=0
for item in m["items"]:
    for take in item["takes"]:
        p=out/take["file"]
        if not p.exists(): raise SystemExit(f"missing {p}")
        d,sr=sf.read(p)
        assert sr==8000, (p,sr)
        assert d.ndim==1 and len(d)>0
        checked+=1
print("probed takes:", checked)
PY
```

2. **Manifest integrity**:

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python tools/maintainer/generate_maternal_voice.py --verify \
  --out kaine/modules/audition/maternal_voice_data
```

Pass condition: exit status 0; every listed take exists and SHA-256 matches.

3. **Determinism replay**: rerun the identical heavy invocation and require the
   manifest diff to be empty (`git diff --exit-code -- kaine/.../manifest.json`
   plus byte-identical take files). Any SHA drift is a failure and means the
   run is inadmissible; restore the last verified baseline rather than patching
   by hand.

4. **Intelligibility (S5) + prosody retention (S6)**: a recognizer must fail or
   produce unstable/nonsense text; pitch/intensity envelopes across the 300 Hz
   ceiling must remain distinguishable after 8 kHz resampling.

## 5. Stop criteria (abort the render, do not continue)

Stop immediately and record the blocker if any of the following holds:

- `hf cache verify` fails or is absent AND the local v2 checkpoint fails the
  section-3.3 assertions.
- `spk_id` does not contain `sam` or its value is not 3000.
- Render-plan probe (3.4) emits any value violating the manifest contract.
- Any take decodes at a sample rate other than 8000, or with a frame count of
  0, or with a clipping result outside [-1, 1].
- Manifest `format` is not 1, or the file is missing any required field
  (`format, sample_rate, initial_unlocked, texts_sha256, generator,
  reference_voice, items, total_bytes, total_seconds`).
- A second render leaves a different SHA for any previous take, or the
  generator block changes mid-run.
- Free space drops below 10 GiB.
- Any runtime test in section 3.5 fails after the change set is applied.
- A mixed-source manifest would be created (Chatterbox + Sam takes in one
  manifest). This is never allowed; rollback the baseline as a whole.

## 6. Manifest schema continuity (what must not change)

This preflight is a model-selection decision only. The manifest remains
format 1 with the following invariants, all already enforced by
`MaternalVoiceRepertoire.load()`:

- `format == 1`
- `sample_rate == 8000`
- Per-take fields: `file, sha256, frames, seconds, seed, rms_dbfs`
- Top-level fields: `format, sample_rate, initial_unlocked, texts_sha256,
  generator, reference_voice, items, total_bytes, total_seconds`
- Decode contract `file_rate * 2 == sample_rate` (8 kHz takes generated from 24
  kHz source), PCM_16 FLAC, channel count 1.
- No new top-level or take-level fields are added without a separate OpenSpec
  proposal and a runtime test.

Provenance change is confined to the `generator` block: it must name the actual
selected source (HF repo id + revision **or** absolute local checkpoint path),
speaker `sam`, native 24 kHz rate, output 8 kHz, no Perth/watermark claim
(explicit `"none declared"`), and the fixed generation parameters. Reference
material may switch from CMU ARCTIC `slt` to none; that change must be recorded
there and removed only after a full Sam run is green.

## 7. Current blockers (2026-11-16)

1. **No generator implementation.** `generate_maternal_voice.py` only
   implements `--renderer chatterbox`; `--renderer sam` exits before any heavy
   import. Do not claim Sam generation exists.
2. **No HF cache.** `kaineone/Qwen3-TTS-Sam-0.6B` is not cached on this host,
   so any offline run must use the local v2 checkpoint
   (`sam-model-v2/checkpoint-epoch-1`) and state that explicitly.
3. **No `--only` on the render-plan helper**, so single-take subset planning
   cannot go through it. Existing generator `--only` exists but is Chatterbox
   only.
4. **No intelligibility / prosody-retention tests exist yet** (S5, S6). A render
   cannot be accepted without them.
5. **No `SamAdapter` / `VoiceBackend` abstraction** landed. Until it does, any
   implemented generation remains a single hard-coded path and must be labeled as
   such.
6. **Unknown Sam generation parameters on GPU.** Determinism (S4) must be
   demonstrated before a full run; do not assume bit-stable output.
7. **Resource plan.** Sam rendering is GPU-bound; every run must use the capped
   runner and report disk space before and after.

## 8. Recommended next command set (exact, for the next implementation PR)

Do not run these as part of this record; they are the hand-off brief.

```bash
cd /var/home/erik/Projects/kaineone/kaine
# HF path (when a cache is intentionally provided):
#   .venv/bin/hf download kaineone/Qwen3-TTS-Sam-0.6B
# then verify:
.venv/bin/hf cache verify kaineone/Qwen3-TTS-Sam-0.6B
# offline render-plan check:
.venv/bin/python tools/maintainer/render_maternal_voice_sam.py --dry-run --json
# baseline runtime contract:
.venv/bin/pytest -q \
  tests/test_maternal_voice.py \
  tests/test_maternal_voice_build_context.py \
  tests/test_maternal_voice_threads.py \
  tests/test_stimulus_source_maternal_voice.py
```

Changed path: `/var/home/erik/Projects/kaineone/kaine/docs/records/maternal-voice-sam-hf-preflight-2026-11-16.md`.
EOF