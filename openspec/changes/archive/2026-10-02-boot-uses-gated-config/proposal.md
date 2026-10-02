# Boot the configuration the gates checked

## Why
`python -m kaine.cycle` loads its configuration twice. The first load, in `main()`, honours `--profile` and decides the boot mode: the supervision mode, the unattended gate, the research safety net and the data root all read it. `_boot_and_run` then loads the configuration again with no profile argument. When the profile was chosen with `--profile` and `KAINE_PROFILE` is unset, the second load falls back to the base-thesis `thesis_test` profile. The cycle then boots a configuration that no gate evaluated: the gates pass on one module set, and a different one runs. `scripts/probe-host` documents `python -m kaine.cycle --profile tier1`, which hits this path.

## What changes
- `main()` passes the configuration it loaded and checked into `_boot_and_run`, and `_boot_and_run` uses that object instead of loading again. The cycle loads its configuration once per boot.
- `_boot_and_run` keeps loading the configuration itself only when it is called without one (direct callers and tests). That load is unchanged.
- No configuration key, default, or file changes.

## Impact
- Code: `kaine/cycle/__main__.py` (`main`, `_boot_and_run`).
- Tests: a regression test that runs `main()` with `--profile` and no `KAINE_PROFILE`, and checks that the configuration `_boot_and_run` boots is the same object the gates evaluated, carrying the selected profile.
- Specs: `configuration-loading` gains a requirement that the cycle boots the configuration its gates evaluated.
- The running MoC7 study is unaffected: it runs through `kaine.research.ignition_study`, from a pinned image.
