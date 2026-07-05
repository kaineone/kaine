## Why

The KAINE abliterated organ is now **published** under the project's own account —
`kaineone/Qwen3.5-4B-abliterated` (safetensors), `kaineone/Qwen3.5-4B-abliterated-GGUF`
(GGUF), and `kaineone/qwen3.5-4b-abliterated` (Ollama) — Apache-2.0, with an honest
model card. But the codebase still points the language organ at a third-party
placeholder, and a fresh install acquires **no model weights at all**:

- `config/kaine.toml` ships `[lingua].model_id = "huihui_ai/Huihui-Qwen3.5-9B-abliterated-GGUF"`
  (a stand-in), and the eval A/B baseline derives from it — so both run the wrong
  organ until an operator hand-edits the config.
- `scripts/install.sh` installs PyTorch only; the wizard is **guide-only** for the
  model server (`dependencies.py` `kind="guide"`), printing a stale
  `mradermacher/...` link. Nothing downloads the organ. A researcher on fresh
  hardware must manually find, download, and serve the right weights, and the
  served name must exactly match `[lingua].model_id` or the first language call
  404s at boot.

This change makes the **published KAINE organ the shipped default** and gives fresh
installs a **real, consented, hardware-aware download** of it — so "clone → install
→ run" resolves identical weights for every researcher (the reproducibility goal of
the abliterated-organ work), instead of a manual scavenger hunt against a wrong
default.

It implements the repoint/link half (§7) of the `kaine-abliterated-organ`
design-of-record now that publishing (§5) is done, and adds the install-time
acquisition the original change assumed an operator would do by hand.

## What Changes

- **Repoint the shipped default at the published organ.** `[lingua].model_id` →
  the published KAINE organ's served alias (HF-repo-id convention, matching the
  current shipped style). The eval A/B baseline keeps deriving from it (the
  fail-closed anti-drift guard is unchanged), so one edit repoints both runtime and
  evaluation. Stale `huihui_ai/...` / `mradermacher/...` references in wizard
  guidance and docs move to the `kaineone/...` URIs.
- **Add a consented, hardware-aware organ download to the install/wizard.** A new
  step — fired only when the organ is actually needed (lingua enabled), i.e.
  "where appropriate" — that, on explicit consent, runs a **real** download of the
  published weights (real subprocess, real success/failure; never a faked/no-op
  "install"). The acquisition path is selected by detected GPU backend, reusing the
  existing detection: **NVIDIA → the Unsloth Studio direction** (the main path for
  entities), **AMD-only → unsloth-core**. Declining prints the guide and downloads
  nothing.
- **Download the right format for the host's role.** The **GGUF** (served by the
  OpenAI-compatible llama-server) by default; **additionally the safetensors base**
  when on-device voice-alignment (Stage-2) training is enabled, since the trainer
  needs it as `base_model_path`. Nothing extra is pulled for a serve-only host.
- **Turnkey: launch and supervise the model server.** Promote `model_server` from a
  guide-only dependency to a launched **service** (mirroring how `redis`/`qdrant` are
  `kind="command"` with an idempotent bootstrap), via a new
  `scripts/model-server-bootstrap.sh`. It locates the hardware-appropriate server
  binary (Studio's `llama-server` on NVIDIA, the unsloth-core path on AMD), launches
  it against the downloaded GGUF under the **exact alias** in `[lingua].model_id`,
  with chain-of-thought suppressed, on the configured port; it writes a pidfile,
  health-gates on `/v1/models` listing the alias, and supports `start`/`status`/`stop`.
  Where `systemd --user` is available it installs a `Restart=on-failure` unit (durable
  supervision); otherwise it runs a supervised background process. So "clone → install
  → run" needs no manual server start.
- **Close the served-name gap.** Because the bootstrap serves under the exact
  `[lingua].model_id` alias and the wizard **verifies** the server lists that model
  before calling the organ ready, a silent boot-time 404 becomes an actionable setup
  message. The launched server's port is preserved by the GPU pre-boot headroom gate
  (it is a KAINE-owned service, never killed).
- **Record provenance.** The published organ's repo id (and revision when
  resolvable) is recorded as a research covariate via the existing
  `_gather_model_ids()` → run manifest path (no new plumbing; it already reads
  `[lingua].model_id`).

## Impact

- Specs: ADD an `organ-provisioning` capability (shipped default points at the
  published organ; consented hardware-aware download; correct-format selection;
  served-name verification; provenance).
- Code (build phase): `config/kaine.toml` `[lingua].model_id`; a real downloader in
  `kaine/setup/organ.py` (reuse `dependencies.py`/`trainer_provisioning.py` backend
  detection + the `_install_extras` consent/subprocess pattern); a new
  `scripts/model-server-bootstrap.sh` (mirror `redis`/`qdrant` bootstrap ergonomics)
  that launches+supervises the native server; `dependencies.py` `model_server` →
  `kind="command"` running it; wizard step wiring (download → launch → verify); a
  served-model verify probe (reuse the health/`/v1/models` probe); Nexus health
  surfacing of the model-server service; gpu-preflight preserves its port.
- Config + docs: present-tense docs of the download + turnkey-serve step and the
  Studio-vs-core path; the all-modules-off first-boot guard is unaffected (it does
  not constrain `model_id`, and the service is consent-gated, not a module flag).
- Non-goals: adding new quant levels; audio/vision model acquisition; replacing
  Spot's module supervision; booting an entity. (Server **process** supervision is
  in scope via the bootstrap's systemd-user/background-process path.)
