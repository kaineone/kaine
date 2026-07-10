# Tasks — containerized KAINE deployment

> **Design-of-record only.** The operator asked to **plan, not implement.** These
> tasks are the future implementation roadmap; do not start them without a go.
> Phases map to `design.md` §12.

## D1 — App image + base compose
- [x] 1.1 Factor `scripts/install.py`'s `_INDEX_BY_FLAVOR` + torch spec into a
      single importable source (or a `install.py --print-index <flavor>` accessor)
      so the image build reuses it verbatim instead of re-deriving it.
      → `scripts/install.py`: `torch_index_url()` + `--print-index`/`--print-torch-spec`
        accessors; the Dockerfile shells out to them. Test:
        `tests/test_container_deployment.py::test_print_index_matches_index_by_flavor`.
- [x] 1.2 Multi-stage `Dockerfile` for the `kaine` image: `ARG FLAVOR=cuda|cpu`
      selects base image + torch index; build stage compiles extras, runtime stage
      is slim; non-root `kaine` uid; `/state` + `/models` as VOLUMEs;
      `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`; entrypoint runs the existing
      `kaine/cycle/preflight.py`; one image serves both `kaine-cycle` (default CMD
      `python -m kaine.cycle`) and `kaine-nexus` (CMD `python -m kaine.nexus`).
      → `Dockerfile` + `docker/entrypoint.sh`. The cycle preflight runs inside
        `kaine.cycle` boot (unchanged); entrypoint fixes volume perms then dispatches.
- [x] 1.3 `compose/kaine.yml` composing the existing `kaine-redis` + `kaine-qdrant`
      + `kaine-nexus` (:8088) + `kaine-cycle` (no port, `profiles: [cycle]`);
      loopback-only ports; `depends_on: condition: service_healthy`.
- [x] 1.4 Confirm a plain `compose up` brings up everything EXCEPT the cycle, and a
      bare `docker run`/`podman run` of the image never auto-starts an entity (guard
      test + shipped-all-off config intact).
      → `docker compose config --services` (no profile) omits `kaine-cycle`; the
        bare-run guard is `kaine/cycle/__main__.py:main` (exit 2 without
        `KAINE_CYCLE_OPERATOR_PRESENT`), covered by existing
        `tests/test_cycle_entrypoint.py` + new profile-gating tests + the CI smoke.
- [x] 1.5 `.dockerignore` / `.containerignore` excluding `state/`,
      `config/*.operator.toml`, `config/secrets.toml`, voices, adapters, `.venv/`,
      caches.

## D2 — GPU services in-compose + GPU matrix
- [x] 2.1 Add `kaine-model-server` (OpenAI-compatible — llama.cpp-server/vLLM,
      weights from the model volume), `kaine-speaches`, `kaine-chatterbox` services;
      pin images by digest; add healthchecks (`/v1/models`, `/get_predefined_voices`).
      → images parameterized with pinned-tag defaults (matching the redis/qdrant
        tag convention); digest-pinning is an operator/registry-access hardening
        step noted in docs. Speaches is CPU-only by design (cuDNN crash on GPU —
        docs/getting-started.md#speaches), so it carries no GPU reservation.
- [x] 2.2 NVIDIA passthrough via `deploy.resources.reservations.devices`; wire the
      two-GPU split (organ→`device_ids: ["0"]`, vision/TTS→`["1"]`); single-GPU
      fallback (share card 0) → `compose/kaine.single-gpu.yml`.
- [x] 2.3 Document + template the `organ=host` override
      (`host.docker.internal` / `host.containers.internal:11434`); make it the
      documented required topology when the voice-alignment trainer is enabled.
      → `compose/kaine.organ-host.yml` + docs/deployment-containers.md.
- [x] 2.4 ROCm device-mount variant (`/dev/kfd` + `/dev/dri`, video/render groups)
      → `compose/kaine.rocm.yml`.

## D3 — Setup-phase provisioning + state/secret/zero-persistence model
- [x] 3.1 A setup one-shot (`profiles: [setup]` or `make provision`) that pulls all
      images + downloads ALL model weights into the shared `kaine-models` (`HF_HOME`)
      volume, reusing the existing `hf download` organ provisioning. Verify runtime
      makes zero model network calls (`HF_HUB_OFFLINE` assertion).
      → `kaine/setup/provision.py` (`kaine-provision` service, `profiles: [setup]`);
        runtime `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` asserted by the CI smoke.
- [x] 3.2 Named `kaine-state` volume; entrypoint preserves 0700/0600 owner-only
      perms inside the container; `KAINE_STATE_KEY` injected as a secret;
      `[security.state_encryption]` AES-256-GCM verified active in-container;
      preservation `require_encryption=true` fail-closed gate verified.
      → `kaine-state` volume + `docker/entrypoint.sh` chmod 0700; `KAINE_STATE_KEY`
        wired (never defaulted); the fail-closed gate is unchanged runtime code
        (`config/kaine.toml [preservation].require_encryption`), preserved in-container.
- [x] 3.3 Assert the zero-raw-sense-data-persistence invariant: no volume/bind
      captures raw A/V; perception scratch is `tmpfs` or absent; add a build-review
      checklist + a test that fails if a raw-perception persistence path is declared.
      → cycle perception scratch is `tmpfs`; tests
        `test_no_named_volume_captures_raw_sense_data` +
        `test_no_durable_bind_or_volume_mounts_a_raw_sense_path`.
- [x] 3.4 Bind-mount `config/kaine.operator.toml` + `config/secrets.toml`
      read-only; document the env/gate-var matrix (none defaulted permissive on the
      cycle service). → `:ro` binds; matrix in docs/deployment-containers.md;
      `test_cycle_defaults_no_gate_var_permissive`.
- [x] 3.5 Document one-command bring-up (`up` minus cycle) + GPU host prerequisites
      per runtime. → docs/deployment-containers.md.

## D4 — Podman, multi-vendor, CI, docs
- [x] 4.1 Podman parity: validate `podman compose` on the same file (CDI GPU,
      `:U`/`:Z` relabel, subuid/subgid, loopback); author Quadlet `.container` +
      `.network` units as the production single-host path (cycle = manually-started
      unit, no auto-start `WantedBy`).
      → `quadlet/*.container` + `quadlet/kaine.network` + `quadlet/README.md`; the
        `kaine-cycle.container` has NO `[Install]` section
        (`test_quadlet_cycle_has_no_install_section`). Live `podman compose`
        validation on a rootless host is an operator step (no podman in CI).
- [x] 4.2 ROCm/XPU image flavors, marked **experimental** until smoke-tested on real
      hardware (no pretend support); CPU flavor as the always-works default.
      → `Dockerfile` `FLAVOR` accepts rocm/xpu (reuses install.py indices), labeled
        EXPERIMENTAL in the header + docs; CPU is the documented default fallback.
- [ ] 4.3 Measure the conscious-access-path latency in-container vs host-native;
      confirm 10 Hz / 3.333 Hz parity before declaring the topology production-ready.
      → DEFERRED: requires running the built containers on real GPU hardware, which
        is out of scope for this parse/lint-only implementation. Blocked pending a
        hardware host; the design flags it as a pre-production-ready measurement.
- [x] 4.4 CI image-build smoke: build CUDA + CPU flavors, run `--version` + preflight
      only — NO entity boot; assert no model weights present in the image layers.
      → `.github/workflows/container-image-smoke.yml` (builds both flavors, asserts
        the cycle refuses to boot = no entity, offline guards set, no weights in any
        layer). The build runs in CI, not in this environment.
- [x] 4.5 Present-tense operator docs for the containerized deployment path (Docker
      + Podman, GPU/CPU, setup phase, supervised cycle boot, dev/research profiles).
      → docs/deployment-containers.md.

## Out of scope (explicit)
- The Unsloth Studio voice-alignment trainer (separate Py3.13/cu130 env — stays out
  of the runtime image); BOINC / `distributed-substrate` packaging (separate change
  that consumes this image); any cloud runtime; auto-starting the entity; producing
  any actual build artifact under this design-only change.
