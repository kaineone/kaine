# One source for organ, storage and service defaults

## Why

The complexity audit of 2026-10-03 (W3) found the organ address, the model-server key lookup and the free-disk floor spelled out separately at many call sites.
- The organ URL fallback `http://127.0.0.1:11434/v1` appears at 14 sites. Two of them leave out the `/v1`; their consumers tolerate either form.
- `KAINE_MODEL_SERVER_API_KEY` is read at 13 sites.
- A second variable, `KAINE_ORGAN_URL`, names the same organ with its own default.
- The 20 GB free-disk floor is written twice.

A change to any of these defaults has to find every copy, and a missed copy fails quietly.

## What changes

- A new stdlib-only module, `kaine/defaults.py`, holds:
  - `DEFAULT_CHAT_URL`;
  - `MODEL_SERVER_API_KEY_ENV`;
  - `DEFAULT_MIN_FREE_GB`;
  - `lingua_chat_url(config)`, which reads `[lingua].chat_url`, else the default;
  - `model_server_api_key(config)`, which reads `[lingua].api_key`, else the environment, else None.

  It joins the boundary-neutral import contract, so core, modules, evaluation, Nexus and setup can all use it.
- Every call site routes through it, keeping its current precedence. The precedence is the same everywhere today: the config key first, then the environment.
- The hypnos trainer service, which runs in its own container without the config, reads the key through `model_server_api_key(None)`.
- `KAINE_ORGAN_URL` stays as the trainer service's own override, documented in the environment table.
- A test fails if the organ port literal `11434` appears outside `kaine/net.py` and `kaine/defaults.py`.
- The configuration appendix gains a table of environment overrides.

Out of scope:
- **The default port.** 11434 is Ollama's port, and the organ now runs on llama-server. Changing the shipped default port is a behaviour change, recorded as a separate follow-up.
- **`KAINE_STATE_KEY`,** which is left alone.

## Impact

No behaviour change: every default keeps its value and every lookup its precedence. No study is running.
