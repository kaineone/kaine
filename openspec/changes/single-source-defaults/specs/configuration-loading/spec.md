## ADDED Requirements

### Requirement: Organ, key and disk defaults have one source
The organ chat URL default, the model-server API key lookup and the free-disk floor SHALL be defined once, in `kaine/defaults.py`, and every consumer SHALL read them from there. The key lookup SHALL prefer `[lingua].api_key` and fall back to the `KAINE_MODEL_SERVER_API_KEY` environment variable. A missing key SHALL read as None, never as an empty string that a client might send.

#### Scenario: A configured key wins over the environment
- **WHEN** `[lingua].api_key` is set and `KAINE_MODEL_SERVER_API_KEY` is also set
- **THEN** `model_server_api_key(config)` returns the configured key

#### Scenario: The environment fills a missing key
- **WHEN** `[lingua].api_key` is absent or empty and `KAINE_MODEL_SERVER_API_KEY` is set
- **THEN** `model_server_api_key(config)` returns the environment value

#### Scenario: No stray copies of the organ port
- **WHEN** the source tree under `kaine/` is scanned
- **THEN** the literal `11434` appears only in `kaine/net.py` and `kaine/defaults.py`
