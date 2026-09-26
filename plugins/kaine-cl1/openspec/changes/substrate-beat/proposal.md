## Why

Today every consumer of the substrate (the Chronos and Soma models on each step, every oscillator on each publish) runs its own window, so substrate time runs faster than cognitive time, a territory records only the windows its own consumer runs, and on a real-time substrate the consumers serialise on one blocking loop (review finding on kaine #197; foundation task 3.3). Real CL1 hardware is not available to this project, but the plugin should be ready for anyone who has access, so the timing has to be right for real time, not only for the accelerated simulator.

KAINE's `plugin-cycle-hook` change gives plugins the cycle's beat through `on_cycle_tick`. This change uses it.

## What Changes

- **One window per cycle tick.** KAINE calls `on_cycle_tick` on every processing tick (10 Hz by default), not only on experiential broadcasts. Each call closes the current substrate window: stimulation queued since the previous tick is delivered at the start of the next window, and each territory's spikes for the window just closed become that territory's latest observation.
- **Consumers stop driving the clock.** In beat mode, a consumer's step queues its stimulation for the next window and reads its territory's latest completed window. The response to a stimulus therefore arrives one processing tick later (about 100 ms at the default rate), which is how a real culture on a shared loop behaves. Stimulation queued twice for the same territory before a window starts keeps the latest request.
- **Two runners, one semantics.**
  - Accelerated simulator: `on_cycle_tick` runs one window synchronously. Its length is one processing period (`1 / processing_rate_hz` from the tick), so substrate time matches cognitive time.
  - Real time (the simulator's real-time mode, or hardware): a background thread runs the substrate loop continuously; `on_cycle_tick` only marks the window boundary and swaps observations under a lock, so the cycle never waits for the substrate.
- **Standalone behaviour kept.** Until the first `on_cycle_tick` arrives (for example when the plugin is used outside KAINE, or with a KAINE that predates the hook), consumers run their own windows as they do today. The first beat switches the broker to beat mode for the rest of the process, and this is logged.
- **The accelerated-time requirement is relaxed** once beat mode is available: real-time simulator runs become supported and non-blocking. `target = "hardware"` stays refused in this change; enabling it is a separate, reviewed change.

## Non-goals

- Enabling hardware (a separate change with its own welfare gate).
- Changing any module's decode or encoding.

## Impact

- `kaine_cl1/substrate/broker.py` (beat mode, background runner, latest-observation store), `kaine_cl1/plugin.py` (`on_cycle_tick`, relaxing the accelerated-time check), the three backends (read latest, queue for next), tests and `docs/cl1.md`.
- Needs a KAINE with `plugin-cycle-hook`.
