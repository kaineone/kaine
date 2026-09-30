## Why

People who install KAINE have hardware that does not match the development workstation. They may have one GPU or several, from any vendor, or unified memory, or no accelerator. The machine may be shared with other work that needs its own GPU memory, and it may have one small system drive and a larger data drive. The installer has to find out what the host has and ask the operator what KAINE may use, instead of assuming. Five things in the current setup path assume instead of asking:

1. **Devices are assigned without being offered.** The first-run wizard lists only CUDA devices. It then assigns by count: the first GPU gets the organ and sleep training, and the second gets vision. It never asks which devices KAINE may use at all. It does not check the proposed device's free memory, or what else is already using it. A GPU the operator keeps for other work is assigned like any other.
2. **Two sources of truth for services.** The organ server and the speech services take their GPU from separate settings (`KAINE_ORGAN_GPU` / `KAINE_VISION_GPU` in `compose/.env`). The wizard never writes these, so the cycle and its services can disagree about which card is which.
3. **Shared services are invisible.** A service KAINE uses may also serve the operator's other applications; a text-to-speech server is the usual case. Nothing records that a service is shared. When it holds memory the cycle needs, the GPU pre-boot gate asks the operator to "close other GPU programs", which here means breaking their other work.
4. **Growing data has no chosen home.** These are written relative to the working directory, or into container volumes on the system drive:
   - entity state;
   - workspace trajectories;
   - evaluation output;
   - research events;
   - backups;
   - the native Redis and Qdrant data;
   - models.

   There is no way to say where they live. A multi-day run can fill the operating-system drive while a data drive sits empty.
5. **The GPU gate cannot see the host from a container.** Inside a container, the gate lists only processes in the container's own process namespace. When a host process holds the memory, the gate names the container's own process as the consumer.

## What Changes

- **Hardware inventory.** The wizard lists every usable compute device the host probe already recognises: CUDA, ROCm, XPU, MPS, unified memory, and CPU. For each device it shows total and free memory, and the processes holding it where they are visible. It also shows CPU cores and system memory.
- **The operator chooses what KAINE may use.**
  - The operator selects the devices KAINE may use and a CPU thread allowance. These are recorded in `[hardware]` in the operator config.
  - Assignments are proposed only from the allowed set.
  - At runtime, device resolution never returns a device outside it; a request for one falls back within the allowed set, with a warning.
  - With no `[hardware]` section, behaviour is unchanged.
- **Fit-checked proposals.** Each proposed assignment is checked against the device's free memory. When the calibrated catalogue from `module-residency-and-speech-tiers` exists, the check also uses the measured footprints. A proposal that does not fit says so and offers the alternatives: another allowed device, a lighter backend rung, or CPU.
- **One device map.** The wizard writes the device map once, to the operator config. The compose GPU variables and the native service launchers are generated from that same map. The pre-boot check fails when they disagree.
- **Shared services are declared.**
  - The operator can mark an external service as shared with other applications. It is recorded in `[services.<name>].shared = true`.
  - KAINE never stops, restarts or evicts a shared service.
  - When a shared service holds memory the cycle needs, the gate says so by name. It suggests a placement that avoids that device, instead of asking the operator to close it.
- **Storage is chosen.**
  - The wizard lists the mounted filesystems with their free space.
  - It recommends a data root off the system drive when a larger one exists, and asks.
  - `[storage].data_root` relocates all growing data. For compose installs, the wizard writes a local override that binds the growing volumes under the data root.
  - A data root without enough free space is refused.
  - The pre-boot check gains a `Storage` row: free space at the data root against a floor.
- **Honest GPU consumers in containers.** When the gate cannot see host processes, it says the consumer list is container-only and reports the device's used memory. It does not attribute that memory to the container's own process.
- **Unchanged.**
  - The shipped config stays all-off, and the wizard never starts the entity.
  - The GPU gate still never kills a process.
  - Hosts without the new sections behave exactly as today.

## Out of scope

- Memory-driven model swapping. That belongs to `module-residency-and-speech-tiers`, whose fit report this change consumes.
- The browser front end. The new steps are written as steps in `browser-first-run`'s shared step model, so its browser driver renders them when that change lands. Until then, the terminal wizard runs them.

## Capabilities

### New Capabilities
- `data-root`: one operator-chosen root for all growing data, honoured by the cycle, Nexus, the native service launchers and the compose override. Includes a free-space floor at pre-boot.

### Modified Capabilities
- `first-run-wizard`: hardware inventory, operator-chosen devices, fit-checked proposals, one device map, shared services, and storage choice.
- `dynamic-hardware`: runtime device resolution stays within the operator's allowed set.
- `gpu-preflight`: names shared services, and says when the consumer list is container-only.

## Impact

- **Code:**
  - `kaine/setup/wizard.py`: inventory, consent, fit check, storage and shared-service steps.
  - `kaine/hardware.py`: allowed-set enforcement in `resolve_device`, and a per-device consumer probe.
  - `kaine/cycle/preflight.py`: shared services, and container visibility.
  - `kaine/preboot.py`: `Storage` and device-map agreement rows.
  - `kaine/config.py`: `[hardware]`, `[storage]` and `[services.*]` shape validation.
  - A data-root resolver used by the modules and the services that write growing data.
  - `scripts/lib/native-services.sh`, and a generated `compose/*.local.yml` override (the pattern is gitignored).
- **Operator:**
  - Existing installs keep working unchanged.
  - Re-running the wizard offers the new steps, and merges only the keys the wizard owns.
- **Safety:**
  - Nothing is moved, stopped or deleted without an explicit operator choice.
  - Relocating an existing data root copies, verifies, and only then switches. The old copy is left for the operator to remove.
