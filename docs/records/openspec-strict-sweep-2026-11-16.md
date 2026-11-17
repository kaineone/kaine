# OpenSpec strict sweep (2026-11-16)

Commands run from `/var/home/erik/Projects/kaineone/kaine`.

## attention-driven-audition

```
openspec validate attention-driven-audition --type change --strict
```
Result: Change 'attention-driven-audition' is valid
Exit code: 0

## welfare-indicator-response

```
openspec validate welfare-indicator-response --type change --strict
```
Result: Change 'welfare-indicator-response' is valid
Exit code: 0
Info (non-blocking):
- entity-preservation/spec.md: Archive would refuse this delta; target spec is structurally invalid (delta headers outside change spec; requirement outside main ## Requirements section). Requirements currently invisible to validate/list/archive.
- unattended-boot/spec.md: same class of structural issue (delta headers placed in main spec).

## voice-development

```
openspec validate voice-development --type change --strict
```
Result: Change 'voice-development' has issues (invalid under strict)
Exit code: 1
Warnings:
- divergence-assessment/spec.md: ADDED "Divergence assessment includes the voice-distinctiveness arm": requirement text very long (>500 characters).
- sleep/spec.md: ADDED "Voice alignment trains only on a validated preference source, with collapse defences": requirement text very long (>500 characters).
JSON strict result: valid=false (2 warnings, 0 errors).
```
