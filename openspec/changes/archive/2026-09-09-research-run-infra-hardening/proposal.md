## Why

A run-readiness audit for a 48h unattended containerized research run surfaced verified infrastructural gaps that would lose data, block boot, or break provenance:

1. **Missing profiles in the image.** The Dockerfile copies only `config/kaine.toml`; `config/profiles/` is absent from the image. The cycle auto-selects `thesis_test` only if the profiles dir exists, and an explicit `KAINE_PROFILE` raises `ProfileError` in-container. The run cannot boot in a controlled profile.
2. **Ephemeral output.** Only `/app/data/evaluation/runs` is a volume; `data/evaluation/<observer>/` and `data/workspace_trajectory/` live in the container's writable layer and are destroyed on `compose down`. 48h of research output is unrecoverable.
3. **Thin Redis headroom.** `--maxmemory 1gb` with `noeviction` leaves thin margin against the (already-lowered) topos/audition stream caps over 48h. The bus must fail loud — `noeviction` stays — but it needs memory to work with.
4. **Unbounded logs.** No log rotation on any service; docker's default `json-file` driver grows unbounded at 10 Hz INFO over 48h.
5. **Provenance hole.** `git_sha` is `null` in every containerized run manifest: `.dockerignore` excludes `.git` and no git binary is installed, so `compute_git_sha()` returns `None` — poisoning export-eligible data.
6. **Quadlet drift.** `quadlet/kaine-cycle.container` lacks the kaine-runs volume and any `/app/data` mount; a quadlet boot presents Nexus with "manifest absent".
7. **Qdrant healthcheck workaround in the operator overlay.** The committed healthcheck (fixed in compose) should be the correct one so the overlay workaround can be deleted.

## What Changes

- **Image (Dockerfile):** COPY `config/profiles/` alongside `config/kaine.toml`; add `ARG GIT_SHA` baked to `ENV KAINE_GIT_SHA` at build.
- **Compose (compose/kaine.yml):** named volume(s) covering the evaluation and workspace-trajectory roots, mounted on both `kaine-cycle` and `kaine-nexus` (the evaluation tab reads them); raise Redis `--maxmemory` to `4gb` (keep `noeviction`); add `json-file` log rotation (max-size 50m, max-file 3) to every service via a shared YAML anchor; replace the qdrant healthcheck with the bash `/dev/tcp` probe.
- **Code (kaine/experiment/run_context.py):** `compute_git_sha()` falls back to `KAINE_GIT_SHA` env when git lookup fails; compose build args pass the sha.
- **Quadlet (quadlet/kaine-cycle.container):** mount parity with compose (kaine-runs volume + `/app/data` evaluation/workspace-trajectory roots).
- **Docs:** record the deliberate absence of a restart policy on `kaine-cycle` — an entity process never auto-restarts; Spot handles module-level recovery in-process, and a dead cycle is an operator decision. Deployment docs move to present tense.

## Impact

- **Affected code:** `kaine/experiment/run_context.py` (+ tests).
- **Affected infra:** `Dockerfile`, `compose/kaine.yml`, `quadlet/kaine-cycle.container`, operator overlay.
- **Behavior:** containerized runs boot with the selected profile, persist all evaluation and workspace-trajectory output across `compose down`, emit manifests with non-null `git_sha`, and rotate logs; Redis bus keeps failing loud with 4× headroom; quadlet boot reaches parity with compose boot.
- **Compatibility:** `KAINE_GIT_SHA` is a fallback only — local git runs are unaffected. No data schema changes; volume mounts are additive.
- **Non-goal:** changing the cycle's restart policy (none, by design) or relaxing `noeviction`.
