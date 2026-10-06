# Local service clients never use a proxy

## Why
httpx clients trust the environment by default (`trust_env=True`). With `HTTP_PROXY`, `HTTPS_PROXY` or `ALL_PROXY` set, they send even a `http://127.0.0.1` request to the proxy. Lead B reproduced this with httpx 0.28.1: a local server, and a proxy variable pointing at a closed port. With the default the request went to the proxy; with `trust_env=False` it went direct. `urllib.request.urlopen` honours the same variables through its default ProxyHandler.

None of KAINE's clients turn this off. Those clients carry:
- Lingua's prompts (the workspace rendering, and heard speech when transcription is on);
- Audition's raw audio to the speech-to-text server;
- Vox's text;
- the organ API key.

On any host or container with a proxy environment, for example one that Docker's client `proxies` setting configures automatically, the entity's audio and speech would leave the host. That would break the eyes-and-ears zero-persistence promise and the no-cloud-at-runtime rule. This host has no proxy variables set, so the exposure is latent here.

## What changes
- **Every runtime client that talks to a KAINE service ignores proxy variables.** That covers each `httpx.AsyncClient`, `httpx.Client` and module-level `httpx.get`/`post` call in `kaine/`, which pass `trust_env=False`. `trainer_service`'s urllib probe uses an opener with an empty ProxyHandler.
- **Setup-time downloads of public weights and wheels stay proxy-capable,** because a proxy is legitimate there: `kaine/setup/speech_models.py` and `kaine/wheel_index.py`. They are the only allowlisted exceptions.
- **A guard test** parses every module under `kaine/` and fails on any httpx client or request call without `trust_env=False`, and on any `urlopen` outside the allowlist.
- **A real-path test** sets `HTTP_PROXY` and `ALL_PROXY` to a closed port and confirms Lingua's real client still reaches a local server directly.

## Impact
- Specs: a new `local-service-clients` capability.
- Code: the 11 `AsyncClient` sites, `cycle/preflight.py`, `organ_server/served.py`, `setup/__main__.py`, `hypnos/trainer_service.py`, and tests.
- Research impact: none. No module behaviour changes on a host without proxy variables, which includes every run so far.
