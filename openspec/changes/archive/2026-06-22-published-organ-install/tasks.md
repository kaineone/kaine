# Tasks — published-organ-install

> Implements the repoint/link half (§7) of `kaine-abliterated-organ` now that the
> organ is published, and adds the install-time acquisition the original change
> assumed an operator would do by hand. Design-first; boots no entity. The download
> is consent-gated and fires only when lingua is enabled.

## 1. Repoint the shipped default

- [ ] 1.1 `config/kaine.toml` `[lingua].model_id` →
      `"kaineone/Qwen3.5-4B-abliterated-GGUF"` (served alias). Leave
      `[evaluation].chat_model_id` unset (derives + fail-closed, unchanged).
- [ ] 1.2 Update `tests/test_boot_wiring.py` literals that pin the old organ id to
      the published id; **add** an assertion that the shipped `[lingua].model_id` is
      the published `kaineone/...` organ.
- [ ] 1.3 Confirm `test_committed_config_ships_all_modules_disabled` still passes
      (it must not constrain `model_id`).

## 2. Consented, hardware-aware downloader (`kaine/setup/organ.py`)

- [ ] 2.1 `detect_organ_backend()` reusing `trainer_provisioning` backend detection
      → {nvidia/studio, amd/core, none}.
- [ ] 2.2 `plan_organ_download(modules, backend)` → which repo(s)+format(s): GGUF
      always; **+ safetensors iff** `[hypnos.voice_alignment]` Stage-2 enabled.
      Returns the exact command(s) + a size estimate; nothing for a non-lingua install.
- [ ] 2.3 `run_organ_download(plan, *, consent)` — **real** `hf download` (or
      `ollama pull` on the Ollama path); `subprocess.run(check=True)` caught; reports
      real success/failure; logs resolved repo revision (sha) when available. NEVER a
      faked/no-op success.
- [ ] 2.4 `verify_served_alias(chat_url, model_id)` — probe `{chat_url}/models`
      (reuse the health probe); returns listed/missing + the served names seen.

## 3. Turnkey serve — Python core + thin shell wrapper

- [ ] 3.0 `kaine/setup/model_server.py` holds the testable logic: locate-binary,
      build-launch-cmd, supervision-mode select, health-check, `start`/`status`/`stop`
      (entry: `python -m kaine.setup.model_server <cmd>`). `scripts/model-server-bootstrap.sh`
      is a thin wrapper over it, mirroring `redis`/`qdrant` ergonomics (idempotent;
      `--help`).
- [ ] 3.1 Locate the server binary for the backend (Studio `llama-server` on NVIDIA,
      unsloth-core build on AMD); honor an explicit override (`KAINE_MODEL_SERVER_BIN`);
      if absent → print the install guide + exit non-zero (no silent multi-GB install).
- [ ] 3.2 Launch: `-m <gguf> --alias <[lingua].model_id> --host 127.0.0.1
      --port <from chat_url> --jinja --reasoning-budget 0` (CoT suppressed).
- [ ] 3.3 Supervise: `systemd --user` `Restart=on-failure` unit where available, else
      a supervised background process + pidfile under `state/model-server/`.
      `status`/`stop` both paths.
- [ ] 3.4 Health-gate: poll `{chat_url}/models` until the alias is listed or time out
      with a clear message.

## 4. Wizard wiring

- [ ] 4.1 New wizard step after module selection (mirror `_install_extras`
      orchestration): if lingua enabled → show plan + bytes → on consent run the
      download, then the server bootstrap launch; on decline print the guide. Never
      crash the wizard on failure.
- [ ] 4.2 Run `verify_served_alias` after launch; on mismatch print an actionable
      "served name X ≠ configured Y" message (not a boot-time 404).
- [ ] 4.3 `kaine/setup/dependencies.py`: `model_server` → `kind="command"` running the
      bootstrap; update steps + link from `mradermacher/...` to
      `huggingface.co/kaineone/Qwen3.5-4B-abliterated-GGUF`.

## 5. Lifecycle integration

- [ ] 5.1 `gpu-preboot-headroom`: confirm the launched server's port is in the
      preserved KAINE-services set (never killed as a foreign consumer); add a test.
- [ ] 5.2 Nexus health: surface the model-server service (up/down, served alias,
      port) in the diagnostics panel (mirror the existing service-health blocks).

## 6. Provenance (mostly automatic)

- [ ] 6.1 Confirm `_gather_model_ids()` records the published id (it reads
      `[lingua].model_id`); add the resolved repo revision to the manifest when the
      downloader captured it. Test the covariate round-trips.

## 7. Docs + validate

- [ ] 7.1 Present-tense docs: the download + turnkey-serve step, the
      Studio(NVIDIA)/core(AMD) path, the GGUF-vs-safetensors matrix (serve-only vs
      Stage-2 training), the served-alias requirement, and `start`/`status`/`stop`.
      Replace stale `huihui_ai/`/`mradermacher/` links with `kaineone/...` across `docs/`.
- [ ] 7.2 `.venv/bin/pytest -q` green (new downloader/verify/plan/bootstrap-wiring
      tests with mocked subprocess + mocked `/v1/models`; never-kills-server test).
- [ ] 7.3 `openspec validate published-organ-install --strict`.
- [ ] 7.4 Confirm shipped `config/kaine.toml` still ships all modules off and the
      first-boot guard passes.
