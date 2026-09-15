## ADDED Requirements

### Requirement: Remote access is verified before the headless switch
The dedication procedure SHALL require remote shell access (SSH) to be enabled AND verified by
an actual successful login from a separate device BEFORE the host's default systemd target is
changed from a graphical target to a non-graphical target (for example `multi-user.target`),
and SHALL NOT instruct the target change until that verification has succeeded.

#### Scenario: Verified login gates the target switch
- **WHEN** the operator has enabled the SSH service, confirmed it is enabled and active, and
  completed a successful login from a separate device
- **THEN** the procedure authorizes changing the default target to the non-graphical target and
  rebooting into it

#### Scenario: Target switch attempted without verified remote access
- **WHEN** the operator reaches the target-switch step without a recorded successful remote
  login from a separate device
- **THEN** the procedure instructs the operator to stop and complete remote-access verification
  first, stating that getting this order wrong can permanently forfeit access to the machine
  and require a monitor-and-keyboard recovery trip

#### Scenario: Remote access fails verification
- **WHEN** the SSH service does not accept a remote login during verification
- **THEN** the procedure directs the operator to keep the graphical default target and resolve
  remote access before dedicating the host

### Requirement: Service reboot survival is verified through lingering
The procedure SHALL enable lingering for the user account that owns the rootless systemd user
units (for example `loginctl enable-linger <user>`) before reboot survival is relied upon,
SHALL verify survival by rebooting the host and confirming the services are active with no
interactive login having occurred, and the deployment documentation SHALL NOT claim reboot
survival for rootless user services unless the lingering prerequisite is stated and met.

#### Scenario: Lingering enabled and survival verified by reboot
- **WHEN** lingering is enabled for the owning user (`loginctl show-user` reports `Linger=yes`)
  and the host is rebooted without any interactive login
- **THEN** the rootless user units are active after boot, and the procedure records this
  post-reboot check as the evidence for reboot survival

#### Scenario: Power cut with lingering never enabled
- **WHEN** the host loses power and lingering was never enabled for the user owning the rootless
  units
- **THEN** the user units do not start at boot and every service stays down until a human logs
  in, and the runbook identifies this state as a reboot-survival defect corrected by enabling
  lingering

#### Scenario: Reboot-survival claim carries its prerequisite
- **WHEN** the deployment documentation describes the rootless quadlet path as surviving
  reboots
- **THEN** it also states the lingering prerequisite and the post-reboot verification step, so
  the claim is not presented as unconditional

### Requirement: Performance profile persists across reboot
The procedure SHALL set the host's performance profile to the intended mode AND verify
persistence by reading the active profile after an actual reboot; the currently active value
alone SHALL NOT be treated as sufficient evidence, because a persisted configuration default
that disagrees with the active mode silently reverts at the next boot with no error and no log
line.

#### Scenario: Profile verified after an actual reboot
- **WHEN** the operator sets the intended performance profile and then reboots the host
- **THEN** the procedure requires re-reading the active profile after boot and confirming it
  equals the intended mode before the host is declared dedicated

#### Scenario: Profile silently reverts on reboot
- **WHEN** the active profile is the intended high-performance mode while the persisted
  configuration default names a lower mode, and the host reboots
- **THEN** the host comes up in the lower mode, the runbook's post-reboot check detects the
  mismatch, and the procedure instructs correcting the persisted default rather than only
  re-issuing the runtime command

#### Scenario: Mismatch blocks dedication
- **WHEN** the post-reboot check finds the active profile differs from the intended mode
- **THEN** the procedure does not declare the host dedicated until the persisted default is
  corrected and a further reboot confirms the profile persists

### Requirement: Swap is configured as an OOM safety valve
A host dedicated to a continuously-running KAINE instance SHALL have swap configured and
enabled at boot, sized against the host's memory budget, with `vm.swappiness` set low (10) and
persisted; on a host with fast persistent storage the swap SHALL be a swapfile on that storage
rather than zram, and the runbook SHALL state that reasoning and note that zram remains correct
where persistent storage is slow.

#### Scenario: Swapfile created and tuned on fast storage
- **WHEN** the operator follows the runbook on a host with fast persistent storage and ample
  free space (worked example: 8 GB unified memory with hundreds of GB free on NVMe)
- **THEN** a swapfile is created on that storage, sized against the memory budget, activated at
  boot, and `vm.swappiness=10` is applied and persisted

#### Scenario: Host with no swap is flagged
- **WHEN** a host being dedicated has no swap of any kind (`swapon --show` is empty and no zram
  unit exists)
- **THEN** the runbook flags this as a gap to close before dedication, because a memory spike
  would otherwise be met by the OOM killer with no safety valve

#### Scenario: zram where storage is slow
- **WHEN** the host's persistent storage is slow (for example eMMC)
- **THEN** the runbook presents zram as the appropriate choice there and does not present the
  swapfile preference as universal

### Requirement: Dashboard is reachable over the private network while bound to loopback
The procedure SHALL make the operator dashboard reachable from the operator's other devices at
a stable address over the operator's private network by proxying to the existing loopback bind
(worked example: `tailscale serve --bg` in front of the `127.0.0.1` bind), SHALL NOT widen the
service's bind address or published port beyond loopback, and SHALL use a name-based stable
address that persists across changes to the host's private-network address.

#### Scenario: Proxy provides reachability without widening the bind
- **WHEN** the operator enables dashboard reachability through the private-network proxy
- **THEN** the dashboard is reachable at a stable HTTPS address from other devices on the
  operator's private network while the `[nexus]` host setting and the container's
  `PublishPort` still bind only to loopback on the host

#### Scenario: Widening the bind is rejected
- **WHEN** an operator considers making the dashboard reachable by changing the bind or
  `PublishPort` to `0.0.0.0`
- **THEN** the runbook directs the operator to the proxy approach instead, preserving loopback
  as defence in depth

#### Scenario: Address stays stable across node address changes
- **WHEN** the host's address on the private network changes (for example a tailnet node's
  100.x address is reassigned)
- **THEN** the dashboard address the operator uses continues to resolve, because it is a
  MagicDNS-style name on the private network rather than the raw address

### Requirement: Dashboard exposure preserves the privacy boundary
Exposing the dashboard over the private network SHALL NOT change its content boundary:
`[nexus] dev_content_override` SHALL remain `false` (it gates raw message text, beliefs, memory
bodies, internal speech, and affect reasons), and `conversation_enabled` SHALL remain `false`
unless the operator deliberately changes it, because a dashboard served over the private
network is reachable from every device on that network.

#### Scenario: Boundary flags unchanged by exposure
- **WHEN** the operator completes the dashboard-exposure procedure
- **THEN** `[nexus] dev_content_override` is still `false` and `conversation_enabled` is still
  `false`, and the runbook states this is required because the dashboard is now reachable from
  every device on the private network

#### Scenario: Deliberate change is explicit and informed
- **WHEN** an operator wants raw content visible on the exposed dashboard
- **THEN** the runbook requires a deliberate, explicit configuration change with the privacy
  consequence stated, and the exposure procedure itself never alters these flags

### Requirement: Operator runbook exists and is discoverable
The repository SHALL include an operator runbook for dedicating a machine as a 24/7 headless
host for a continuously-running KAINE instance (covering host prerequisites, verified remote
access before the headless switch, reboot survival via lingering, performance-profile
persistence, swap policy, dashboard reachability, and the dashboard privacy boundary), and the
documentation hub SHALL link to it so it is discoverable alongside the install and
service-bring-up documentation.

#### Scenario: Runbook linked from the docs hub
- **WHEN** a reader opens the documentation hub
- **THEN** a link to the headless-host dedication runbook is present under its operations
  section, distinct from the install and service-bring-up documentation

#### Scenario: Runbook verifies rather than assumes
- **WHEN** the runbook is read end to end
- **THEN** each critical step includes an explicit verification (remote login, post-reboot
  service state, post-reboot profile, swap presence, dashboard reachability) and names the
  failure modes of silent profile reversion and non-starting rootless units

### Requirement: Procedure is host-agnostic with labelled worked examples
The dedication procedure SHALL be written to apply to any Linux host being dedicated to a 24/7
KAINE instance; host-specific commands SHALL appear only inside clearly-labelled worked
examples; the documentation SHALL NOT state or imply that KAINE requires a Jetson or any other
specific hardware; and the existing dual-GPU x86_64 workstation path SHALL remain the default
and SHALL NOT be regressed or complicated by this capability.

#### Scenario: Jetson commands confined to a labelled example
- **WHEN** the runbook explains a generic step such as performance-profile persistence
- **THEN** the normative instruction is hardware-neutral, and Jetson-specific commands
  (`nvpmodel`, JetPack tooling) appear only inside a clearly-labelled worked example

#### Scenario: Workstation path unaffected
- **WHEN** an operator follows the existing dual-GPU x86_64 workstation documentation
- **THEN** that path is unchanged and remains the default, and the headless-host runbook is
  presented as an additional path for dedicating a host rather than a replacement