# Proposal — `module-ignition-study`

## Why

The base thesis says the mind is the workspace's competition and broadcast among predictive processors. A direct way to see what each faculty adds is to watch the same material again and again while the faculties are added one at a time, and compare what reaches the workspace. That means the ignitions: which coalitions win and are broadcast, how often, and with which members.

The operator's study, 2026-09-26:
1. Spawn a base-thesis entity: Soma, Chronos, Topos, Audition and Lingua, with Syneidesis and Volition.
2. Let it gestate in the local womb under the default gate.
3. At birth into its audio/video world, show it one fixed four-film programme, then freeze and preserve it.
4. Revive it with one more module and show it the same programme again.
5. Repeat until all sixteen modules are on.
6. Compare the ignitions across viewings.

A readiness audit of main found that the study cannot run yet. It needs revive-into-a-running-cycle, a birth path for an entity without sleep or a body, complete snapshots, film-aligned ignition records, handling for the film's end, and two confound fixes. This change is the study protocol, and it tracks those prerequisite changes. The operator also wants the full entity running on this desktop, on a Jetson Orin Nano Super, and under Termux on a Pixel 6a. That is the portability program's later phases, tracked here as the hardware leg.

## What changes

- **Programme.** Four public-domain color films with dialogue, and no racism in their plots, always in this order:
  1. *First Spaceship on Venus* (1960)
  2. *Gulliver's Travels* (1939)
  3. *Santa Claus Conquers the Martians* (1964)
  4. *Baby Huey: Quack-a-Doodle-Doo* (1950)

  One checksummed playlist manifest.
- **Two lines.** Both are forked from the post-gestation preservation.
  - The **main line** adds one module per viewing.
  - The **control line** re-watches the same number of times with no module added.

  Main minus control separates each module's effect from familiarity. Each line has its own state root, memory collections and bus database, so the two beings never share state.
- **Module order after the base five:** Thymos, Mnemos, Hypnos, Phantasia, Nous, Eidolon, Empatheia, Vox, Praxis, Perception, Mundus.
  - Mundus comes last, when the operator offers a body.
  - Faculties that add no input channel on this host are recorded as such, not skipped: Praxis without effectors, Perception without locus requests, and the Mundus stub body.
- **A study runner** drives each step:
  1. revive with the step's module set;
  2. play the programme;
  3. preserve at the end;
  4. stop;
  5. record the step's manifest.
- **An analysis** compares the ignitions per viewing: broadcast rate, coalition size and membership by module, salience, and alignment to film position, as main-versus-control differences per step.

## Prerequisite changes (tracked in tasks)

1. `operator-revive-and-preserve`
2. `faculty-relative-birth`
3. `snapshot-completeness`
4. `film-aligned-ignition-log`
5. `film-end-preserve`
6. `study-confounds`

## Hardware leg (tracked in tasks)

Portability program phases 1–4: an any-target installer, native services, torch-free and JAX-free backends, and residency and swap. The goal is a full entity on the desktop and the Orin Nano Super, and under Termux on the Pixel 6a.

## Impact

- New capability `module-ignition-study`.
- New tooling: the study runner and the analysis. No change to the entity's cognition.
- Two preserved beings are created. The study never deletes a being.
