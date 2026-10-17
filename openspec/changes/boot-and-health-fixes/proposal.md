## Why

A live test boot of main (e266aa88) found three operational defects in the first container bring-up.

1. The dashboard health page reported every module disabled while the cycle ran seven. `load_health_prober` read the configuration with `load_kaine_config`, which applies no module profile, while the cycle reads it with `load_runtime_config`, which applies the `first_configuration` profile by default.
2. The first `docker compose up` on an empty state volume failed with "failed to mkdir .../_data/sleep: file exists", and a second `up` worked. The image ships `/app/state/sleep/voice_align_jobs`, so the runtime copies that tree into a new named volume at container creation, and the dashboard and the cycle both do it at once. The same race exists for the two Quadlet units.
3. Every dashboard container left an empty anonymous volume, because the image declares `VOLUME /models` and the dashboard mounted nothing there.

## What Changes

- `load_health_prober` loads its configuration through `load_runtime_config` (the cycle's loader), with the profiles directory taken beside the configuration file, so module enablement on the health page matches the cycle.
- The Dockerfile no longer creates `/app/state/sleep/voice_align_jobs` in the image. `/app/state` stays, kaine-owned and empty, so a fresh volume still inherits its owner and mode but there is no content to copy and nothing to race over. This one change fixes Compose and Quadlet alike, with no start-order coupling between services. The cycle and the preboot check create the jobs directory when they need it; the compose cycle already uses `/trainer-jobs`.
- The Compose dashboard service and the Quadlet dashboard unit mount the shared models volume read-only at `/models`, so the image's `/models` volume is always backed by a named volume and no anonymous volume is created.

## Capabilities

### New Capabilities

- `container-deployment`: first bring-up on an empty volume is race free and creates no anonymous volumes.

### Modified Capabilities

- `dashboard-health`: module enablement on the health page follows the cycle's configuration loader.

## Impact

`kaine/dashboard/health/config.py`, `Dockerfile`, `compose/kaine.yml`, `quadlet/kaine-dashboard.container`, and their tests. Existing deployments keep their volumes; nothing is removed.
