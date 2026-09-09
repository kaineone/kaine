## Phase 1 — Image

- [ ] 1.1 `Dockerfile`: add `COPY config/profiles /src/config/profiles` (or copy the full `config` dir including `profiles/`) so profiles reach the image and `KAINE_PROFILE` / thesis_test auto-selection work in-container
- [ ] 1.2 `Dockerfile`: add `ARG GIT_SHA` and bake it as `ENV KAINE_GIT_SHA=${GIT_SHA}` in the runtime stage
- [ ] 1.3 Verify (`.dockerignore` review) that `.git` stays excluded — no repo data must leak into the image

## Phase 2 — Compose (compose/kaine.yml)

- [ ] 2.1 Add named volume(s) covering the research output roots (`/app/data/evaluation` — including `runs` — and `/app/data/workspace_trajectory`); mount them on **both** `kaine-cycle` and `kaine-nexus` (the evaluation tab reads them); add to the top-level `volumes:` section
- [ ] 2.2 Raise Redis `--maxmemory` from `1gb` to `4gb`; explicitly keep `noeviction` (the bus must fail loud, not silently evict)
- [ ] 2.3 Add a YAML anchor `x-logging: &default-logging` with driver `json-file`, `max-size: "50m"`, `max-file: "3"`; apply `logging: *default-logging` to **every** service
- [ ] 2.4 Fix the qdrant healthcheck in compose/kaine.yml itself: `test: ["CMD", "bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/6333"]` (image ships no wget/curl; bash /dev/tcp connect is the readiness signal; qdrant binds 6333 only once serving)
- [ ] 2.5 Pass `GIT_SHA` through compose `build.args` (e.g. from shell `git rev-parse --short HEAD`) to the Dockerfile `ARG`
- [ ] 2.6 Delete the qdrant healthcheck workaround from the operator overlay (config/kaine.operator.toml or overlay compose file) once compose is correct

## Phase 3 — Code (git sha provenance)

- [ ] 3.1 `kaine/experiment/run_context.py`: `compute_git_sha()` falls back to `os.environ.get("KAINE_GIT_SHA")` (validated non-empty string) when the git subprocess lookup fails or returns `None`; keep the function best-effort/never-raises
- [ ] 3.2 Tests (`tests/experiment/test_run_context.py` or sibling): cover (a) git lookup success ignores env, (b) git failure falls back to `KAINE_GIT_SHA`, (c) git failure with unset/empty env returns `None`
- [ ] 3.3 Run the test suite; confirm no regressions in run-context/manifest tests

## Phase 4 — Quadlet parity

- [ ] 4.1 `quadlet/kaine-cycle.container`: add the kaine-runs volume mount and the `/app/data` evaluation + workspace-trajectory volume mounts to match compose (`Volume=kaine-runs.volume:/app/data/evaluation/runs` plus the new named volumes)
- [ ] 4.2 Confirm `%h/projects/kaine` host paths align with the compose bind mounts so a quadlet boot sees the same manifest/output state as compose
- [ ] 4.3 Verify no `[Install]` section or auto-restart is introduced (see Phase 5)

## Phase 5 — Docs

- [ ] 5.1 Document the deliberate **absence of a restart policy** on `kaine-cycle`: an entity process never auto-restarts; Spot handles module-level recovery in-process; a dead cycle is an operator decision. Record in the deployment docs and/or a comment block in compose/kaine.yml + quadlet/kaine-cycle.container
- [ ] 5.2 Update deployment docs (docs/deployment.md or equivalent) to present tense for the newly-fixed items: profiles in-image, durable evaluation/workspace-trajectory volumes, Redis 4gb maxmemory (noeviction retained, fail-loud), log rotation, baked GIT_SHA provenance, qdrant healthcheck rationale
- [ ] 5.3 Update the run-readiness audit checklist (if present) to mark the seven verified gaps resolved, with pointers to the fixed files
