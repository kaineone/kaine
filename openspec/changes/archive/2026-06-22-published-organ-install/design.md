# Design — published-organ-install

## What's actually there today (grounding)

- **Runtime resolution.** `kaine/modules/lingua/client.py` (`OpenAIChatClient.complete`)
  posts `{"model": <model_id>, ...}` verbatim to `{chat_url}/chat/completions`. KAINE
  does **not** launch the server and does **not** validate the model string — the
  server matches it against what it has loaded, else 400/404. Shipped
  `[lingua].model_id = "huihui_ai/Huihui-Qwen3.5-9B-abliterated-GGUF"`,
  `chat_url = "http://127.0.0.1:11434/v1"`.
- **Eval baseline.** `kaine/evaluation/config.py` derives `chat_model_id` from
  `lingua_model_id` and **raises** if an explicit value differs (the A/B-divergence
  anti-drift guard). `kaine/cycle/__main__.py` wires this at boot (exit 3 on
  mismatch). → repointing `[lingua].model_id` alone repoints both.
- **Install.** `scripts/install.sh` / `install.py` install PyTorch + `pip install -e .`
  only — **no model download**. `kaine/setup/dependencies.py` lists `model_server` as
  `kind="guide"` (prints steps, probes port 11434, never runs a command) with a stale
  `mradermacher/...` link. `kaine/setup/trainer_provisioning.py` detects backend and
  guides **CUDA→Unsloth Studio** / **ROCm→unsloth-core**, never auto-installing.
- **Provenance.** `kaine/cycle/__main__.py` `_gather_model_ids()` already reads
  `[lingua].model_id` into the run manifest (`run_context.py`), exported in the
  metrics-only bundle. No new plumbing needed.
- **Guard.** `tests/test_boot_wiring.py::test_committed_config_ships_all_modules_disabled`
  checks module toggles + `[spot]`/`[research_submission]` only — it does **not**
  constrain `model_id`. Safe to repoint.

## The served-name convention (resolves the 404 gotcha)

The shipped style is **HF-repo-id-as-served-alias** (`huihui_ai/...-GGUF`). We keep
it: `[lingua].model_id = "kaineone/Qwen3.5-4B-abliterated-GGUF"`, and the launch
guidance starts llama-server with that exact `--alias`. The wizard then probes
`{chat_url}/models` and confirms the alias is listed before declaring the organ
ready. This converts the current failure mode (server up, wrong name, boot 404 on
the first cycle) into a pre-boot, operator-facing "served name X ≠ configured Y" message.

## Download: real, consented, hardware-aware

A new `kaine/setup/organ.py` with the acquisition logic, wired as a wizard step that
fires **only when lingua is enabled** ("where appropriate"):

1. **Detect** the GPU backend (reuse `trainer_provisioning` detection): NVIDIA(cuda),
   AMD(rocm), or other.
2. **Choose the path** — the operator's stated direction:
   - **NVIDIA → Unsloth Studio** (main path for entities): the organ is acquired into
     the Studio-adjacent location the served llama-server reads.
   - **AMD-only → unsloth-core**: the core-compatible acquisition.
   - Neither available → guide only (no silent install).
3. **Choose the format(s)** for the host's role:
   - **GGUF always** (`kaineone/Qwen3.5-4B-abliterated-GGUF`) — what the
     OpenAI-compatible server serves.
   - **+ safetensors** (`kaineone/Qwen3.5-4B-abliterated`) **iff** `[hypnos.voice_alignment]`
     Stage-2 training is enabled — the trainer's `base_model_path`. (Serve-only hosts
     skip the ~8 GB safetensors.)
4. **Consent + real run.** Show the exact command and bytes-to-download; run only on
   explicit consent (mirror `_install_extras` orchestration: `subprocess.run(check=True)`
   caught, never crash the wizard). The download is a **real** `hf download` (or `ollama
   pull` on the Ollama-served path) reporting real success/failure — no faked "installed"
   message. Decline → print the guide, download nothing.
5. **Verify** the served alias is listed (step above) once the operator has the server up.

### Turnkey: launch + supervise the server (operator-chosen)

"Install → run" should need no manual server start, so `model_server` is promoted
from `kind="guide"` to `kind="command"` — the same shape `redis`/`qdrant` already
use (an idempotent bootstrap run on consent). The difference: redis/qdrant are docker
containers (`docker compose up -d`, restart handled by the daemon); the model server
is a **native long-running GPU process** (Studio's `llama-server`, typically
`~/.unsloth/llama.cpp/build/bin/llama-server`; the unsloth-core build on AMD), so its
lifecycle is ours to own.

The heavy logic (binary discovery, launch-command construction, supervision mode
selection, health-gating) lives in **testable Python** — `kaine/setup/model_server.py`
— with `scripts/model-server-bootstrap.sh` as a **thin wrapper** that calls
`python -m kaine.setup.model_server <start|status|stop>`. This keeps the redis/qdrant
"one bootstrap command" ergonomics while making the non-trivial logic unit-testable
with mocks (the same Python-core / thin-entry split the extras/deps install already
uses), rather than burying it in untestable shell.

`scripts/model-server-bootstrap.sh` (mirrors the redis/qdrant bootstrap ergonomics —
idempotent, `--help`, `status`, `stop`):

1. **Locate the server binary** for the detected backend (NVIDIA → Studio llama-server;
   AMD → unsloth-core build); honor an explicit override; if absent, print the
   install guide and exit non-zero (no silent install of the multi-GB env — that
   principle stands; we launch what's installed, we don't fabricate it).
2. **Launch** it against the downloaded GGUF: `-m <gguf> --alias <[lingua].model_id>
   --host 127.0.0.1 --port <from chat_url> --jinja --reasoning-budget 0`
   (CoT suppressed — the organ is a voice; matches the validated serving flags).
3. **Supervise.** Where `systemd --user` is available, install a `Restart=on-failure`
   unit (durable across crashes/logout-linger) — the robust path. Otherwise run a
   supervised background process with a pidfile under `state/model-server/`. Provide
   `status`/`stop` either way. This is **process** supervision of a service, distinct
   from Spot (which supervises cognitive **modules**); the two do not overlap.
4. **Health-gate.** Poll `{chat_url}/models` until the alias is listed (or time out
   with a clear message). The cycle's existing health probe + the wizard verify step
   both consume this.

**GPU coordination.** The launched server is a KAINE-owned service: the
`gpu-preboot-headroom` gate already preserves KAINE services by port probe, so the
server's port is in the preserved set and is **never** killed as a foreign consumer.
The gate still fails closed if total VRAM is short.

**Nexus.** Surface the model-server service (up/down, served alias, port) in the
diagnostics/health panel, mirroring the existing service-health blocks.

Why not fold this into Spot: Spot freezes/restarts modules inside the cycle process
group and escalates on repeated failure — it is not a service launcher and has no
notion of a native GPU server binary. systemd-user/background supervision is the
right, smaller tool and keeps the model server alive independent of the cycle
lifecycle (so the organ is warm before the cycle boots and survives a cycle restart).

## Format choice rationale

- The runtime serves **GGUF** via the OpenAI-compatible llama-server (the shipped
  `chat_url` + the current GGUF-repo default establish this). So GGUF is the
  always-needed artifact.
- The **safetensors** are only needed as the Stage-2 trainer base (`base_model_path`)
  and for non-llama.cpp inference (vLLM/transformers). Gating the ~8 GB pull on
  `voice_alignment` being enabled keeps serve-only installs lean.

## Config

```toml
[lingua]
chat_url = "http://127.0.0.1:11434/v1"
model_id = "kaineone/Qwen3.5-4B-abliterated-GGUF"   # published KAINE organ (served alias)
```

`[evaluation].chat_model_id` stays unset → derives from `[lingua].model_id`
(fail-closed on explicit mismatch, unchanged). No module flag flips → the
all-modules-off first-boot guard is unaffected.

## Provenance

No new plumbing: `_gather_model_ids()` already records `[lingua].model_id` as
`model_ids["lingua"]` (and `evaluation_chat`) in the run manifest. Once the default
is the published id, every run records the published organ as a covariate. The
downloader additionally logs the resolved repo revision (commit sha) when `hf`
reports it, so a run can pin the exact published snapshot.

## Alternatives considered

- **Leave install guide-only, just repoint the link.** Minimal, but leaves the
  "fresh hardware has no organ" gap the operator explicitly asked to close. Rejected.
- **Bake weights into the repo / a release asset.** Multi-GB in git; defeats the
  point of publishing to HF/Ollama. Rejected.
- **Download in `install.sh`.** Wrong layer — the script has no module-selection
  context, so it can't know if lingua is enabled or if Stage-2 is on. The wizard does.
  Keep heavy logic in Python (mirrors the existing dependency/extras split).
- **Supervise the server with Spot instead of systemd/background.** Spot supervises
  cognitive modules inside the cycle process group, not native service binaries, and
  tying the organ's lifecycle to the cycle would kill the warm organ on every cycle
  restart. Rejected in favor of service-level supervision.
- **Run the server in docker (like redis/qdrant).** A GPU llama-server in a container
  adds CUDA/ROCm passthrough complexity for no benefit when the Studio/core build is
  already a native binary on the host. Rejected; reuse the installed native server.

## Risks

- **Wrong format for an exotic server (vLLM wants safetensors).** Mitigated: the
  format selection is explicit and documented; vLLM users enable the safetensors pull
  (or it comes with Stage-2). Document the matrix.
- **Download size / partial pulls.** `hf download` resumes and verifies; we surface
  bytes up front and report real failure (no false success).
- **Served-name drift.** The verify-probe catches it pre-boot instead of at the first
  cycle's first utterance.
