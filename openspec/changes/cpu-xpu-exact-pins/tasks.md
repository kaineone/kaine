## 1. Resolver

- [x] 1.1 Add `resolve_fixed_flavor` for cpu and xpu (newest in-range torch per architecture, companions, torchaudio preference, refusal when unpublished, release-timing pairing warning when torchaudio is requested).
- [x] 1.2 Add `--flavor cpu|xpu` to the CLI.

## 2. Installers

- [x] 2.1 install.sh and install.py resolve and pin cpu and xpu exactly; refuse an unpublished xpu architecture before installing torch.
- [x] 2.2 The torchaudio keep/replace rule uses the cpu/xpu pins; mps keeps the unpinned path.

## 3. Docs and tests

- [x] 3.1 docs/accelerator-provisioning.md states cpu/xpu pinning and mps being unpinned.
- [x] 3.2 Resolver tests: cpu x86_64 and aarch64, xpu x86_64, xpu aarch64 refusal, torchaudio preference.
- [x] 3.3 Installer parity tests: cpu pins in both installers; a matching CPU torchaudio is kept on re-run; xpu aarch64 refused in both.
