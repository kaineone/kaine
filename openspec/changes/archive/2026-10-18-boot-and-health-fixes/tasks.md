## 1. Implementation

- [x] 1.1 Load the health prober's configuration through `load_runtime_config`, with the profiles directory beside the configuration file
- [x] 1.2 Drop `/app/state/sleep/voice_align_jobs` from the image so a fresh state volume has nothing to copy
- [x] 1.3 Mount the models volume read-only on the Compose dashboard service and the Quadlet dashboard unit
- [x] 1.4 Tests: the health prober enables the first_configuration modules and honours an explicit profile and the operator overlay; the Dockerfile creates no content under `/app/state`; every service built from the image mounts a volume at each image `VOLUME` path
