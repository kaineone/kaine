# State-root validation guide — 2026-11-16

## Scope

How to run a validation boot of `python -m kaine.cycle` against the entity's
state without mutating the frozen production `state/` tree, and without touching
the production identity or world-model weights.

## Supported knobs

There is **no dedicated state-root environment variable**. The cycle hard-codes
the relative path `state/` in `kaine/cycle/__main__.py` (e.g.
`resolve(Path("state"))`). Redirection is therefore done by redirecting the
growing-data root, which `kaine.storage.resolve()` applies to every relative
`state/...` path.

Environment variables:

- `KAINE_DATA_ROOT` — absolute path of the directory under which the relative
  `state/` tree is placed. Highest priority (`kaine.storage.configured_data_root`).
- `KAINE_MODELS_DIR` — maps paths beginning with `state/models` onto that
  directory (use this to keep the original read-only weights in use).
- `KAINE_TRAINER_JOBS_DIR` — maps `state/sleep/voice_align_jobs`.
- `KAINE_STATE_KEY` — AES-256 state-encryption key (hex/32 bytes). Must match
  the key used to write the copied state, or decryption fails.
- `KAINE_PROFILE`, `KAINE_TIER`, `KAINE_STUDY` — module/tier/study overlays.

Config knobs (`config/kaine.toml` / `config/kaine.operator.toml`):

- `[storage].data_root` — same effect as `KAINE_DATA_ROOT` but committed/overlaid.
- `[storage].min_free_gb`
- `[preboot].state_root` (default `"state"`) and `[preboot].data_root`
  (default `"data"`). These are growing-data keys, so a relative value is
  resolved under the data root; an absolute value is kept as-is. The cycle's
  own hard-coded `state` path still depends on the data root above.
- `[preboot].extra_disk_paths`

## Blocking condition: prior welfare freeze

The production `state/cycle/control.json` carries a `welfare` freeze holder.
`python -m kaine.cycle` therefore logs

    entity is frozen at boot (source=welfare)

and maintenance (welfare) sleeps are not initiated, so the matured completion
bound cannot be measured. This freeze is by design a named freeze that only an
explicit override clears. **Do not override it in the production tree.**

## Safe procedure (isolated clone)

Run from `/var/home/erik/Projects/kaineone/kaine`. State is ~1.3 GiB.

1. Prepare a scratch data root:

```bash
export KAINE_STATE_KEY="$(cat secrets/state_key)"
SCRATCH=/home/erik/.claude/scratchpad/kaine-validation-2026-11-16
mkdir -p "$SCRATCH"
rsync -a --exclude='models' state/ "$SCRATCH/state/"
```

The original `state/models` is deliberately not copied; the run reads the
original weights through `KAINE_MODELS_DIR` and never writes to them.

2. Release the welfare freeze **only in the clone**:

```bash
KAINE_DATA_ROOT="$SCRATCH" \
KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
KAINE_STATE_KEY="$KAINE_STATE_KEY" \
.venv/bin/python -m kaine.cycle.control override welfare
```

This rewrites `$SCRATCH/state/cycle/control.json` and leaves production
`state/cycle/control.json` untouched.

3. Validation boot:

```bash
timeout 90 env \
  KAINE_DATA_ROOT="$SCRATCH" \
  KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
  KAINE_STATE_KEY="$KAINE_STATE_KEY" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle > /tmp/kaine-validation-boot.log 2>&1
```

All `state/...` paths now resolve under `$SCRATCH/state/`; reads of weights
resolve to the original read-only `state/models`. Production identity and the
world-model checkpoint are not read for writes and are not modified.

4. Inspect `/tmp/kaine-validation-boot.log` for `sleep.sleep.started` /
   `sleep.sleep.completed` (trigger `welfare_rest`) and maintenance-sleep
   durations.

5. Cleanup after measurement:

```bash
rm -rf "$SCRATCH"
```

If the boot succeeded, the scratch tree is disposable; keep it only while
investigating failures. Production state is unchanged.

## How to avoid touching identity / world model

- Never run the override against production `state/` (no `KAINE_DATA_ROOT`
  set, or data root equal to the project root).
- Always verify the effective location before a write-sensitive command:
  `echo "$KAINE_DATA_ROOT"`; it must be the scratch path.
- Keep `KAINE_MODELS_DIR` pointed at the original `state/models` so weights
  are read, not duplicated; do not copy models into the scratch tree.
- The copy includes identity and world-model files for load/read access. The
  cycle may update the world-model checkpoint **inside the clone only**; the
  production checkpoint under `state/world_model/` is untouched because it is
  not on any resolved write path in this procedure.
- If desired, make the production tree read-only for the duration of the
  experiment (`chmod -R u-w state` then restore), but this alone does not
  provide a clean unfrozen boot; the clone procedure above is still required.
```