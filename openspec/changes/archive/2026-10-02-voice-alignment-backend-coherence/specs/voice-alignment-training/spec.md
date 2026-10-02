## ADDED Requirements

### Requirement: Hot-swap modes are paired with the backends that can serve them
Boot SHALL refuse `[hypnos.voice_alignment].hot_swap_mode = "organ_adapter"` unless `trainer_backend = "job_queue"`, because only the trainer service converts an accepted adapter to the GGUF form the organ loads. Every trainer backend SHALL dispatch the configured hot swap after it promotes an accepted adapter; a failed notification SHALL be logged and SHALL NOT undo the promotion.

#### Scenario: An unservable pairing is refused
- **WHEN** voice alignment is enabled with `trainer_backend = "subprocess"` and `hot_swap_mode = "organ_adapter"`
- **THEN** boot refuses with a configuration error naming both keys

#### Scenario: The subprocess backend notifies the server
- **WHEN** the subprocess trainer reports an accepted, promoted adapter and `hot_swap_mode = "reload_endpoint"`
- **THEN** the configured reload endpoint is notified with the promoted adapter's path

### Requirement: The GPU window does not bracket job-queue training
The on-device GPU window SHALL NOT unload and reload the model server around `job_queue` training, because the trainer service runs in its own container and waits for the organ to report that it is asleep and that the GPU has room. The window result SHALL record why it did not bracket.

#### Scenario: Job-queue training on one GPU
- **WHEN** a sleep trains with `trainer_backend = "job_queue"` on a single-GPU host
- **THEN** the model server is neither stopped nor restarted by the cycle, and the window result names the job queue as the reason
