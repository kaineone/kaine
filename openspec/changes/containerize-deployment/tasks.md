# Tasks — containerized KAINE deployment

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go.
> Phases map to `design.md` §12.

## D1 — App image + base compose
- [ ] 1.1 Factor `scripts/install.py`'s `_INDEX_BY_FLAVOR` + torch spec into a
      single importable source (or a `install.py --print-index <flavor>` accessor)
      so the image build reuses it verbatim instead of re-deriving it.
- [ ] 1.2 Multi-stage `Dockerfile` for the `kaine` image: `ARG FLAVOR=cuda|cpu`
      selects base image + torch index; build stage compiles extras, runtime stage
      is slim; non-root `kaine` uid; `/state` + `/models` as VOLUMEs;
      `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`; entrypoint runs the existing
      `kaine/cycle/preflight.py`; one image serves both `kaine-cycle` (default CMD
      `python -m kaine.cycle`) and `kaine-nexus` (CMD `python -m kaine.nexus`).
- [ ] 1.3 `compose/kaine.yml` composing the existing `kaine-redis` + `kaine-qdrant`
      + `kaine-nexus` (:8088) + `kaine-cycle` (no port, `profiles: [cycle]`);
      loopback-only ports; `depends_on: condition: service_healthy`. For this first
      step the cycle talks to host-native model-server/STT/TTS.
- [ ] 1.4 Confirm a plain `compose up` brings up everything EXCEPT the cycle, and a
      bare `docker run`/`podman run` of the image never auto-starts an entity (guard
      test + shipped-all-off config intact).
- [ ] 1.5 `.dockerignore` / `.containerignore` excluding `state/`,
      `config/*.operator.toml`, `config/secrets.toml`, voices, adapters, `.venv/`,
      caches.

## D2 — GPU services in-compose + GPU matrix
- [ ] 2.1 Add `kaine-model-server` (OpenAI-compatible — llama.cpp-server/vLLM,
      weights from the model volume), `kaine-speaches`, `kaine-chatterbox` services;
      pin images by digest; add healthchecks (`/v1/models`, `/get_predefined_voices`).
- [ ] 2.2 NVIDIA passthrough via `deploy.resources.reservations.devices`; wire the
      two-GPU split (organ→`device_ids: ["0"]`, vision/TTS→`["1"]`); single-GPU
      fallback (share card 0).
- [ ] 2.3 Document + template the `organ=host` override
      (`host.docker.internal` / `host.containers.internal:11434`); make it the
      documented required topology when the voice-alignment trainer is enabled.
- [ ] 2.4 ROCm device-mount variant (`/dev/kfd` + `/dev/dri`, video/render groups).

## D3 — Setup-phase provisioning + state/secret/zero-persistence model
- [ ] 3.1 A setup one-shot (`profiles: [setup]` or `make provision`) that pulls all
      images + downloads ALL model weights into the shared `kaine-models` (`HF_HOME`)
      volume, reusing the existing `hf download` organ provisioning. Verify runtime
      makes zero model network calls (`HF_HUB_OFFLINE` assertion).
- [ ] 3.2 Named `kaine-state` volume; entrypoint preserves 0700/0600 owner-only
      perms inside the container; `KAINE_STATE_KEY` injected as a secret;
      `[security.state_encryption]` AES-256-GCM verified active in-container;
      preservation `require_encryption=true` fail-closed gate verified.
- [ ] 3.3 Assert the zero-raw-sense-data-persistence invariant: no volume/bind
      captures raw A/V; perception scratch is `tmpfs` or absent; add a build-review
      checklist + a test that fails if a raw-perception persistence path is declared.
- [ ] 3.4 Bind-mount `config/kaine.operator.toml` + `config/secrets.toml`
      read-only; document the env/gate-var matrix (none defaulted permissive on the
      cycle service).
- [ ] 3.5 Document one-command bring-up (`up` minus cycle) + GPU host prerequisites
      per runtime.

## D4 — Podman, multi-vendor, CI, docs
- [ ] 4.1 Podman parity: validate `podman compose` on the same file (CDI GPU,
      `:U`/`:Z` relabel, subuid/subgid, loopback); author Quadlet `.container` +
      `.network` units as the production single-host path (cycle = manually-started
      unit, no auto-start `WantedBy`).
- [ ] 4.2 ROCm/XPU image flavors, marked **experimental** until smoke-tested on real
      hardware (no pretend support); CPU flavor as the always-works default.
- [ ] 4.3 Measure the conscious-access-path latency in-container vs host-native;
      confirm 10 Hz / 3.333 Hz parity before declaring the topology production-ready.
- [ ] 4.4 CI image-build smoke: build CUDA + CPU flavors, run `--version` + preflight
      only — NO entity boot; assert no model weights present in the image layers.
- [ ] 4.5 Present-tense operator docs for the containerized deployment path (Docker
      + Podman, GPU/CPU, setup phase, supervised cycle boot, dev/research profiles).

## Out of scope (explicit)
- The Unsloth Studio voice-alignment trainer (separate Py3.13/cu130 env — stays out
  of the runtime image); BOINC / `distributed-substrate` packaging (separate change
  that consumes this image); any cloud runtime; auto-starting the entity; producing
  any actual build artifact under this design-only change.
