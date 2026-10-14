## 1. Mounts

- [ ] 1.1 `compose/kaine.yml`: the cycle mounts `kaine-trainer-jobs` at `/trainer-jobs` and sets `KAINE_TRAINER_JOBS_DIR=/trainer-jobs`.
- [ ] 1.2 The sleep factory reads `KAINE_TRAINER_JOBS_DIR` when set and uses it for the jobs directory; the run manifest records the resolved path.
- [ ] 1.3 Check the quadlet tmpfs at `/app/state/perceptual_locus` is writable by uid 10001 under rootless Podman, and set its mode if not.

## 2. State rename

- [ ] 2.1 Before the first step, check write access to every directory a step writes into (the nearest existing ancestor for one not created yet); refuse with exit code 14 and a message naming the directory, owner, mode and the fix (`chown -R`). The mount-point check (2.2) runs first.
- [ ] 2.2 When the old side holds data and the new side is an empty mount point, the refusal says so.
- [ ] 2.3 Tests for both, mutation-checked.

## 3. Upgrade test and docs

- [ ] 3.1 A container test: an old-layout tree in a named volume, the image's own user and the shipped mounts; the rename completes and a second start is a noop.
- [ ] 3.2 Docs: the volumes table in `docs/07-deployment/containers.md`, the upgrade notes in appendix E.
- [ ] 3.3 `openspec validate compose-state-mount-ownership --strict`.
