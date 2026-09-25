#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# Install the KAINE Quadlet units into the user's systemd generator directory.
#
# Behaviour:
# - Renders every quadlet/*.container, *.network and *.volume from ROOT into DEST.
# - Replaces the @KAINE_ROOT@ placeholder with the checkout's absolute path.
# - Skips any unit whose basename contains "unattended".
# - Refuses a ROOT path with unsafe characters (anything outside
#   /[A-Za-z0-9._/+-]/) or that is not absolute.
# - Refuses when config/kaine.operator.toml, config/secrets.toml or compose/.env
#   is missing, naming the bootstrap step that creates each.
# - Verifies the rendered units with the podman quadlet generator if found.
# - Never enables, starts, or restarts any unit.
#
# Options:
#   --root DIR       checkout root (default: the checkout containing this script)
#   --dest DIR       quadlet directory (default: $XDG_CONFIG_HOME/containers/systemd)
#   --dry-run        render and verify, but do not write anything
#   --generator PATH quadlet generator to use, or "none" (default: auto)
#
# Usage:
#   bash scripts/install-quadlet.sh
#   bash scripts/install-quadlet.sh --dry-run
#
# After install, reload systemd, start the data services, and start the entity
# only deliberately with operator presence:
#   systemctl --user daemon-reload
#   systemctl --user start kaine-redis kaine-qdrant kaine-nexus
#   systemctl --user set-environment KAINE_CYCLE_OPERATOR_PRESENT=1
#   systemctl --user start kaine-cycle

set -euo pipefail

DEFAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DEFAULT_DEST="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd"

ROOT=""
DEST=""
DRY_RUN=0
GENERATOR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      [[ $# -ge 2 ]] || { echo "install-quadlet: --root requires an argument" >&2; exit 2; }
      ROOT="$2"; shift 2 ;;
    --dest)
      [[ $# -ge 2 ]] || { echo "install-quadlet: --dest requires an argument" >&2; exit 2; }
      DEST="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --generator)
      [[ $# -ge 2 ]] || { echo "install-quadlet: --generator requires an argument" >&2; exit 2; }
      GENERATOR="$2"; shift 2 ;;
    --help|-h) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$ROOT" ]] && ROOT="$DEFAULT_ROOT"
[[ -z "$DEST" ]] && DEST="$DEFAULT_DEST"

if ! ROOT_RESOLVED="$(cd "$ROOT" && pwd -P)"; then
  echo "install-quadlet: root path does not exist or is not a directory: $ROOT" >&2
  exit 1
fi

if [[ ! "$ROOT_RESOLVED" =~ ^/[A-Za-z0-9._/+-]+$ ]]; then
  echo "install-quadlet: refusing unsafe root path: $ROOT_RESOLVED" >&2
  exit 1
fi

missing=()
if [[ ! -f "$ROOT_RESOLVED/config/kaine.operator.toml" ]]; then
  missing+=("config/kaine.operator.toml: copy config/kaine.toml and edit it, see docs/getting-started.md")
fi
if [[ ! -f "$ROOT_RESOLVED/config/secrets.toml" ]]; then
  missing+=("config/secrets.toml: run bash scripts/redis-bootstrap.sh to create it")
fi
if [[ ! -f "$ROOT_RESOLVED/compose/.env" ]]; then
  missing+=("compose/.env: run bash scripts/redis-bootstrap.sh and bash scripts/qdrant-bootstrap.sh")
fi

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "install-quadlet: refusing incomplete checkout at $ROOT_RESOLVED" >&2
  for item in "${missing[@]}"; do
    echo "  missing $item" >&2
  done
  exit 1
fi

STAGE="$(mktemp -d)"
GEN_ERR_FILE="$(mktemp)"
trap 'rm -rf "$STAGE" "$GEN_ERR_FILE"' EXIT

rendered=()
shopt -s nullglob
for src in "$ROOT_RESOLVED/quadlet/"*.container "$ROOT_RESOLVED/quadlet/"*.network "$ROOT_RESOLVED/quadlet/"*.volume; do
  name="$(basename "$src")"
  if [[ "$name" == *unattended* ]]; then
    echo "skipped $name (never installed by this script)"
    continue
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '%s\n' "${line//@KAINE_ROOT@/$ROOT_RESOLVED}"
  done < "$src" > "$STAGE/$name"

  if grep -q '@KAINE_ROOT@' "$STAGE/$name"; then
    echo "install-quadlet: placeholder remains in staged $name" >&2
    exit 1
  fi

  rendered+=("$name")
done
shopt -u nullglob

if [[ ${#rendered[@]} -eq 0 ]]; then
  echo "install-quadlet: no quadlet units found in $ROOT_RESOLVED/quadlet" >&2
  exit 1
fi

EXPLICIT=0
GEN=""

if [[ -n "$GENERATOR" ]]; then
  GEN="$GENERATOR"
  EXPLICIT=1
elif [[ -n "${KAINE_QUADLET_GENERATOR:-}" ]]; then
  GEN="$KAINE_QUADLET_GENERATOR"
  EXPLICIT=1
fi

if [[ "$EXPLICIT" -eq 0 ]]; then
  for cand in /usr/libexec/podman/quadlet /usr/lib/podman/quadlet; do
    if [[ -x "$cand" ]]; then
      GEN="$cand"
      break
    fi
  done
fi

run_generator() {
  if ! QUADLET_UNIT_DIRS="$STAGE" "$GEN" -user -dryrun >/dev/null 2>"$GEN_ERR_FILE"; then
    echo "install-quadlet: quadlet generator rejected the rendered units:" >&2
    cat "$GEN_ERR_FILE" >&2
    exit 1
  fi
}

if [[ "$GEN" == "none" ]]; then
  : # verification skipped by request
elif [[ "$EXPLICIT" -eq 1 && ! -x "$GEN" ]]; then
  echo "install-quadlet: generator not executable: $GEN" >&2
  exit 1
elif [[ -n "$GEN" && -x "$GEN" ]]; then
  run_generator
elif [[ "$EXPLICIT" -eq 0 ]]; then
  echo "quadlet generator not found; skipped verification"
else
  echo "install-quadlet: generator not executable: $GEN" >&2
  exit 1
fi

if [[ $DRY_RUN -eq 1 ]]; then
  for name in "${rendered[@]}"; do
    echo "would install $name"
  done
  exit 0
fi

mkdir -p "$DEST"
for name in "${rendered[@]}"; do
  tmp="$DEST/$name.tmp.$$"
  cp "$STAGE/$name" "$tmp"
  mv -f "$tmp" "$DEST/$name"
  echo "installed $name"
done

cat <<'EOF'

Next steps:
  systemctl --user daemon-reload
  systemctl --user start kaine-redis kaine-qdrant kaine-nexus
  systemctl --user set-environment KAINE_CYCLE_OPERATOR_PRESENT=1
  systemctl --user start kaine-cycle

The entity unit kaine-cycle is started only deliberately after asserting
operator presence with set-environment.
EOF
