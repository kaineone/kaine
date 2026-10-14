## Why

The post-rename test boot of 2026-10-14 upgraded a pre-rename state tree under the compose deployment, and the start stopped with exit code 14:

```
kaine.cycle: state rename failed: PermissionError: [Errno 13] Permission denied: '/app/state/hypnos/adapters' -> '/app/state/sleep/adapters'
```

`compose/kaine.yml` mounts the `kaine-trainer-jobs` volume at `/app/state/sleep/voice_align_jobs`, inside the `kaine-state` volume. When the state volume already holds an entity, as every upgraded deployment does, it has no `sleep/` directory yet, so the container runtime creates `/app/state/sleep` as the parent of the mount point, owned by root with mode 0755. The cycle runs as the non-root `kaine` user (uid 10001) and cannot create entries in that directory, so the boot-time state rename cannot move `hypnos/*` into `sleep/`. A probe with plain named volumes reproduced it outside the test setup: the image user cannot write to `/app/state/sleep`. A fresh, empty volume is not affected, because Docker copies the image's own `sleep/` directory, owned by `kaine`, into it on first use.

The refusal is safe: the manifest stays in progress, nothing has moved, and the start resumes once the directory is writable (the test boot then migrated all 21 steps and ran). But every existing compose deployment, including the operator's own, would stop at its first start after the upgrade, with a raw `PermissionError` that does not say what to do.

The same boot found a smaller wording problem. A native-layout tree started under the compose mounts was refused with "both hypnos/voice_align_jobs and sleep/voice_align_jobs exist under /app/state and hold data", although the new side was an empty mount point. The refusal is correct, since a rename cannot land on a mount point, but the message names the wrong reason.

## What Changes

- **The trainer-jobs volume moves out of the state volume.** The cycle mounts `kaine-trainer-jobs` at `/trainer-jobs`, as the study runner and the trainer already do, so nothing is nested under `/app/state` except the perceptual-locus tmpfs, whose target directory already exists in the volume.
- **The cycle finds the jobs directory from the environment.** The sleep factory reads `KAINE_TRAINER_JOBS_DIR` when it is set and uses it for `[sleep.voice_alignment].trainer_jobs_dir`, the same container-only override pattern as `KAINE_DATA_ROOT`. Compose sets it to `/trainer-jobs` for the cycle.
- **The state rename checks write access first.** Before the first step, `rename_state` checks that it can write every directory a step writes into. If one is not writable, the start stops with exit code 14 and a message that names the directory, its owner and mode, and the command that fixes it for a volume, instead of a `PermissionError` in the middle of the plan.
- **The refusal names a mount point as a mount point.** When the old side holds data and the new side is an empty mount point, the message says that the new side is a mount point a move cannot land on and asks the operator to move the old content into the mounted volume.
- **A container upgrade test.** A test builds an old-layout tree in a named volume, starts the image as its own user with the shipped mounts, and checks that the rename completes and a second start finds nothing to do.

## Capabilities

### New Capabilities

### Modified Capabilities

- `containerized-deployment`: an existing state volume upgrades without a manual ownership fix.
- `entity-preservation`: the state rename refuses before its first move when it cannot write a destination.

## Impact

- **Code:** `compose/kaine.yml`, `kaine/boot/factories/sleep.py`, `kaine/lifecycle/rename_state.py`, tests in `tests/test_container_deployment.py` and `tests/test_rename_state*.py`.
- **Operators:** a deployment upgraded before this change ships keeps its jobs where they are: the volume is the same, only its mount point moves. A deployment already stopped by the refusal starts once `/app/state/sleep` is given to uid 10001 (`docker run --rm -v kaine-state:/s alpine chown 10001:10001 /s/sleep`), which the new message prints.
- **Quadlet:** the quadlet units mount no volume inside `/app/state` apart from the tmpfs, so they are not affected; the change checks that a rootless Podman tmpfs at `/app/state/perceptual_locus` is writable by the image user.
- **Docs:** `docs/07-deployment/containers.md` (volumes table) and appendix E's upgrade notes.
