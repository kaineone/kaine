## Why

Real CL1 hardware is not available to this project, and may never be. The plugin should still be ready for anyone who does have access, so that a funded group can test KAINE's forward models on living cultures without rebuilding the plumbing. Since the substrate beat (kaine #201) the timing is ready: one window per cycle tick on a background thread, in real time, without blocking the cycle. What remains is a deliberate, reviewed way to point the plugin at a real CL1, which today it refuses outright.

`docs/biological-welfare.md` commits this package to four things once tissue is in the loop: institutional oversight, stimulation limits treated as safety limits, keeping the entity's welfare and the culture's welfare as separate questions, and characterising every pattern in the simulator first. This change enforces what code can enforce and states plainly what it cannot.

## What Changes

- **`target = "hardware"` becomes possible, behind a gate.** The plugin accepts it only when all of these hold, and otherwise refuses to load with a message naming what is missing:
  - a `[plugins.cl1.hardware]` table whose `welfare_acknowledgement` equals, exactly, the statement "I have read plugins/kaine-cl1/docs/biological-welfare.md and hold institutional approval for work with this culture";
  - a non-empty `ethics_reference` in that table (the operator's approval or protocol reference);
  - `accelerated_time = false` (accelerated time is simulator-only);
  - no `data_source` set (simulated data sources have no meaning on hardware).
- **The session confirms it is really hardware.** With `target = "hardware"`, opening the session refuses when `cl.is_simulator()` reports the simulator, just as `target = "simulator"` already refuses when a real device is present.
- **Every hardware boot says so.** The plugin logs at WARNING, on every boot, that a living neural culture is in the loop and names the ethics reference.
- **Freeze safety.** While KAINE's cycle is frozen (including a welfare freeze), no ticks arrive, so no stimulation is delivered. Stimulation queued before a freeze is discarded, not delivered late, when the first tick after it arrives: any beat that comes more than two processing periods after the previous one clears the queued stimulation before the window boundary. The real-time loop also caps the spikes it holds for an open window, keeping only the most recent window-length of activity, so a long freeze cannot grow memory without bound.
- **A lagging real-time substrate is visible.** A beat that arrives before the previous window boundary was consumed is counted and logged at WARNING (the first, then every 100th), as the accelerated path already does.
- **Cortical Cloud stays refused**, with the existing reason.
- **Docs.** `docs/cl1.md` gains a "Running on a CL1" section for owners: the plugin drives the device through Cortical Labs' own SDK in-process, so KAINE and the plugin run on the machine that has the device SDK; the configuration block; what the gate checks; and what remains the operator's responsibility (approval, culture care, and characterising patterns in the simulator first).

## Non-goals

- Verifying an institutional approval. The plugin records the attestation and the reference; it cannot check them, and the docs say so.
- Cortical Cloud.
- Changing stimulation encoders or limits (they already stay inside the SDK's ceilings and are enforced at the broker).

## Impact

- `kaine_cl1/config.py` (the `hardware` table), `kaine_cl1/plugin.py` (the gate, the boot warning), `kaine_cl1/substrate/session.py` (the hardware check), `kaine_cl1/substrate/broker.py` (stale-stimulation discard, spike cap, real-time overrun warning), tests with a stubbed non-simulator SDK, `docs/cl1.md`, `docs/biological-welfare.md` (point to the gate).
