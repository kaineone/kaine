## ADDED Requirements

### Requirement: Nexus access mode
Nexus SHALL support `[nexus].access` with values `"open"` and `"token"`, overridable by `KAINE_NEXUS_ACCESS`. The committed configuration SHALL ship `"open"`. An invalid value SHALL fail startup with an error naming the allowed values.

**Open mode:**
- Every surface, read and state-changing, SHALL work without a token or sign-in.
- `/login` SHALL redirect to the landing console.
- At startup, Nexus SHALL log once, at INFO, that it is open to anyone who can reach it, and list the accepted hosts.

**Token mode** SHALL behave exactly as before: bearer token or session, with the session key required for state-changing requests.

**In both modes:**
- The Host allowlist and the Origin/CSRF validation SHALL apply to every request.
- A non-loopback bind SHALL still require `non_loopback_allowed`.

#### Scenario: Open mode needs no sign-in
- **WHEN** `access = "open"` and a browser on the same machine opens `/diagnostics/`
- **THEN** the page and its privileged reads succeed with no token or session

#### Scenario: Open mode still refuses foreign hosts
- **WHEN** `access = "open"` and a request arrives with a Host header that is not in the allowlist
- **THEN** it is rejected

#### Scenario: Open mode still refuses cross-origin writes
- **WHEN** `access = "open"` and a state-changing request carries an Origin that is not allowed
- **THEN** it is rejected

#### Scenario: Token mode is unchanged
- **WHEN** `access = "token"` and a request has no token or session
- **THEN** privileged surfaces are refused exactly as before

### Requirement: Tailnet hosts can reach Nexus
`KAINE_NEXUS_EXTRA_HOSTS`, a comma-separated list of host names or addresses, SHALL be added to the Host allowlist. For each entry, its `http://` and `https://` origins, with and without the configured and published ports, SHALL be added to the allowed origins. Entries SHALL be validated as host names or IP literals; an invalid entry SHALL fail startup naming it.

#### Scenario: Served over the tailnet
- **WHEN** `KAINE_NEXUS_EXTRA_HOSTS` names the machine's tailnet host and a tailnet browser opens `https://<that host>/diagnostics/` through `tailscale serve`
- **THEN** the Host and Origin checks accept it

### Requirement: The root address leads to a console
When the conversation console is not mounted, a request for `/` SHALL redirect to the landing console instead of returning 404.

#### Scenario: Observed study
- **WHEN** conversation is disabled and an operator opens `http://127.0.0.1:8088/`
- **THEN** the response redirects to `/diagnostics/`

### Requirement: Read-only mode refuses every control
Nexus SHALL support `[nexus].read_only` (default false), overridable by `KAINE_NEXUS_READ_ONLY`. When it is true, Nexus SHALL refuse every request whose method is not GET, HEAD or OPTIONS with HTTP 403, before routing and in every access mode. Pages SHALL show a banner saying controls are off. A study viewer SHALL run Nexus in read-only mode, because some controls (the cycle rate) reach a running entity through its bus.

#### Scenario: A rate change against a watched study is refused
- **WHEN** `read_only` is true and a client POSTs to `/diagnostics/cycle/rates`
- **THEN** the response is 403 and nothing is published to `cycle.control`

#### Scenario: Viewing still works
- **WHEN** `read_only` is true and a browser opens `/diagnostics/`
- **THEN** the page renders with the read-only banner
