# Proposal — `module-ignition-study`

## Why

The base thesis says the mind is the workspace's competition and broadcast among predictive processors. A direct way to see what each faculty adds is to show the same being the same material while the faculties differ, and compare what reaches the workspace. That means the ignitions: which coalitions win and are broadcast, how often, and with which members.

The operator's protocol, 2026-09-28:
1. **Gestation.** Spawn one base-thesis entity and let it gestate in the local womb until it is born.
2. **The seed.** At the moment it graduates gestation, preserve it. That snapshot is the seed.
3. **Branch runs.** Revive the seed once per module set, one run at a time, each with one more module in a logical order. Show it the four films after a pleasant transition from the womb, recording everything.
   - Every branch run starts from the same seed and sees the same media, so the runs show how the being diverges with each new faculty.
4. **Accumulating line.** One being gains the next module after each viewing and rewatches the same films, building familiarity.
5. **Noise reference.** A repeat of the base run from the seed shows how much two identical runs differ.
6. **Analysis and write-up.** Compare the recorded data. Look for evidence of workspace ignition or sentient behaviour. Report it truthfully and in full in a new version of the paper and poster, whether or not it shows what was hoped for.

The first version of this change (2026-09-26) forked a main line and a familiarity-control line from the gestation. This revision replaces that line structure with the operator's protocol. The prerequisite changes it tracked are done, and it keeps them.

## What changes

- **Programme.** Four public-domain colour films with dialogue, and no racism in their plots, always in this order:
  1. *First Spaceship on Venus* (1960)
  2. *Gulliver's Travels* (1939)
  3. *Santa Claus Conquers the Martians* (1964)
  4. *Baby Huey: Quack-a-Doodle-Doo* (1950)

  One checksummed playlist manifest, about 243 minutes.
- **Base set.** The operator's base-thesis configuration:
  - the base: Soma, Chronos, Topos, Audition and Lingua, with Syneidesis and Volition;
  - Thymos and Hypnos.
- **Module order.** Mnemos, Phantasia, Nous, Eidolon, Empatheia, Vox, Praxis, Perception, Mundus, up to all sixteen modules.
- **The seed.** One gestation in the local womb under the default gate. Birth is automatic when the gate's conditions hold; no operator acknowledgement delays it.
  - The being is preserved once the birth bloom has completed. That preservation is the seed.
  - The womb's time at birth is recorded, so the transition renders the field the being last perceived.
- **Lines.** Each line has its own working directory and memory collections. Every step starts on an empty bus database.
  - **Branch (k = 0…9).** Revive the seed with the base set plus the first k modules of the order.
  - **Repeat.** A second base run revived from the seed: the noise reference.
  - **Accumulate (k = 1…9).** Step 1 revives branch 0's preservation. Each later step revives the previous accumulate step's preservation, gains the k-th module and rewatches the programme.
- **Each viewing.**
  1. The womb-to-world transition (change `womb-to-world-transition`).
  2. The four films.
  3. Preservation and a stop at the programme's end.
  4. A recorded step manifest.
- **Recording** (change `run-recording`). Every run persists:
  - everything Nexus displays, after the same privacy filter Nexus applies;
  - the research event log;
  - the workspace trajectory;
  - the film-aligned ignition log;
  - Lingua's external utterances.

  Inner speech is never recorded.
- **Hosting.** The study runner runs inside the cycle image as a compose service, so every cycle reaches the bus, the organ and the models the way the containerized cycle does. The study directory lives on a durable volume.
- **Order and schedule.** One run at a time, never two at once:
  1. seed;
  2. branch 0;
  3. repeat;
  4. then branch k followed by accumulate k, for k = 1…9.

  Results arrive progressively. Whatever is complete when the poster locks is reported as complete, and the rest as in progress.
- **Analysis.**
  - Per viewing: the existing content-free ignition measures.
  - The comparisons:
    - branch k against branch 0: a faculty's effect from the same seed;
    - branch 0 against repeat: the noise floor;
    - accumulate k against branch k: familiarity and history.
  - Claude Science may receive only the existing metrics-only bundle, with the operator's consent. No cognitive content leaves the host.

## Prerequisite changes (tracked in tasks)

These are done:
1. `operator-revive-and-preserve`
2. `faculty-relative-birth`
3. `snapshot-completeness`
4. `film-aligned-ignition-log`
5. `film-end-preserve`
6. `study-confounds`

New, for this revision:
- `womb-to-world-transition`
- `run-recording`

## Hardware leg (tracked in tasks)

Portability program phases 1–4. By operator direction (2026-09-28), this leg is paused except for the desktop and, next, the Orin Nano Super.

## Impact

- The study runner, its plan and its analysis change to the seed and branch protocol. No change to the entity's cognition.
- The study creates one seed and one preserved being per run. It never deletes a being.
