# Paracosm Grid — Viewer Connection Guide

## Grid Details

| Field | Value |
|-------|-------|
| Grid name | Paracosm |
| Login URI | `http://<entity-host>:9000/` |
| Login URI (IP fallback) | `http://<tailscale-ip>:9000/` |
| Platform | OpenSimulator 0.9.3.x (.NET 8) |
| Network | Private mesh network only (e.g. Tailscale tailnet; not public internet) |

The viewer machine must be on the same private network as `<entity-host>` to
connect. Replace `<entity-host>` with your host's Tailscale hostname (or any
resolvable private hostname), and `<tailscale-ip>` with your host's Tailscale
IP address. Tailscale is one example of a suitable private mesh; any VPN or
LAN that allows direct TCP/UDP to the host ports works.

## Viewer Grid Manager Setup

In Firestorm (or any SL-compatible viewer), add a custom grid:

1. Open **Preferences → OpenSim** (or **Grid Manager**)
2. Click **Add Grid**
3. Enter: `http://<entity-host>:9000/`
4. Click **Get Grid Info** — it should auto-populate the grid name as "Paracosm"
5. Click **Apply** / **OK**

If DNS resolution for `<entity-host>` fails on the viewer machine, use the
host's IP address (`<tailscale-ip>`) instead.

## Login Credentials

| Field | Value |
|-------|-------|
| First name | Kaine |
| Last name | One |
| Password | *(set during first server boot — ask the grid admin)* |

The login screen grid selector must show **Paracosm** (not Second Life or any other grid).

## Network Ports

The viewer needs outbound access to `<entity-host>` on these ports:

| Port | Protocol | Purpose |
|------|----------|---------|
| 9000 | TCP | Login, HTTP services, capabilities |
| 9010–9021 | UDP | Region simulators (one per region) |
| 5060 | UDP | Voice (FreeSWITCH SIP, when enabled) |

All ports are bound to the private network interface (`<tailscale-ip>`), not `0.0.0.0`.

## Region Map

The continent is a 4×3 grid of 256m regions. All regions share borders — avatars walk freely between them.

```
        x=1000      x=1001      x=1002      x=1003
       ┌───────────┬───────────┬───────────┬───────────┐
y=1002 │ Highlands │  Ruins    │Observatory│ Sanctuary │  ← north
       │ :9018     │ :9019     │ :9020     │ :9021     │
       ├───────────┼───────────┼───────────┼───────────┤
y=1001 │  Meadow   │  Forest   │  Garden   │  Village  │  ← interior
       │ :9014     │ :9015     │ :9016     │ :9017     │
       ├───────────┼───────────┼───────────┼───────────┤
y=1000 │  Welcome  │ Shoreline │ Tidepools │ Driftwood │  ← south coast
       │ :9010     │ :9011     │ :9012     │  Beach    │
       │ (spawn)   │           │           │ :9013     │
       └───────────┴───────────┴───────────┴───────────┘
```

**Welcome** (1000,1000) is the default login region. New logins land here.

## Testing the Connection

From the viewer machine, verify reachability first:

```bash
# Check connectivity
ping <entity-host>

# Check login service is up
curl -s http://<entity-host>:9000/get_grid_info
```

The `get_grid_info` response should return XML containing `<gridname>Paracosm</gridname>`.

## For Programmatic / Bot Access

Login via XMLRPC at `http://<entity-host>:9000/`. The endpoint accepts standard Second Life login protocol (XMLRPC `login_to_simulator` method). LibOpenMetaverse or liblsl-based bots connect identically to SL bots — just point the login URI at `http://<entity-host>:9000/`.

For the cognitive agent bridge (custom viewer), the login flow is:

1. XMLRPC `login_to_simulator` → returns sim IP, port, circuit code, agent ID
2. UDP connect to the assigned region port (9010–9021) on `<entity-host>`
3. Standard SL message protocol from there (CompleteAgentMovement, AgentUpdate, etc.)

## Voice (FreeSWITCH)

When voice is enabled, the SIP endpoint is `<entity-host>:5060`. The viewer receives the voice server address automatically via capability URLs after login — no manual voice configuration should be needed in the viewer if FreeSWITCH is running.
