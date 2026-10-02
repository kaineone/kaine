## 1. Access mode
- [ ] 1.1 `NexusConfig.access` (default `"open"`), read from `[nexus].access` and the `KAINE_NEXUS_ACCESS` environment variable, with validation. `config/kaine.toml` `[nexus]` gets `access = "open"` with a comment.
- [ ] 1.2 `require_operator_token` admits every request in open mode. `/login` (GET and POST) redirects to the landing console in open mode.
- [ ] 1.3 `__main__`: in open mode, no token is required to start. The non-loopback guard keeps requiring `non_loopback_allowed`. Log the one-time INFO line.

## 2. Tailnet hosts and the root address
- [ ] 2.1 `KAINE_NEXUS_EXTRA_HOSTS` extends the host allowlist and the allowed origins (http/https, with and without the port), with validation.
- [ ] 2.2 `/` redirects to the landing console when conversation is not mounted.
- [ ] 2.3 `compose/kaine.yml`: the Nexus service passes `KAINE_NEXUS_ACCESS` (default unset, so the config's `"open"` applies) and `KAINE_NEXUS_EXTRA_HOSTS` (default empty).

## 3. Tests
- [ ] 3.1 Open mode: privileged GET and POST succeed with no token. Login redirects. A foreign Host is rejected. A cross-origin POST is rejected.
- [ ] 3.2 Token mode: the existing auth tests pass unchanged (run them with `access = "token"` where they assume the old default).
- [ ] 3.3 Extra hosts are accepted for Host and Origin; an invalid entry fails startup.
- [ ] 3.4 Root redirect; startup without a token in open mode; a bad access value fails.

## 4. Docs
- [ ] 4.1 An "Opening Nexus" section (address, modes, token locations, tailnet via `tailscale serve`), linked from the README, Getting Started, Operations and the container guide. Correct the stale `~/.kaine/nexus-token` instruction.
