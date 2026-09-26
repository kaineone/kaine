#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
#
# One-line bootstrap for KAINE on any supported host.
#
# Usage:
#   curl -fsSL <repo-url>/scripts/bootstrap.sh | bash -s -- --repo <git-url>
#   bash scripts/bootstrap.sh --repo <git-url>
#
# The script checks git and Python >= 3.11, prints (and optionally runs) the
# system-package command for the host's package manager, clones or updates the
# repo, installs KAINE, bootstraps native services, and offers the first-run
# setup wizard.  It never starts the entity and never assumes root: privileged
# package-manager commands are run via sudo and will prompt the operator.

set -euo pipefail

DEFAULT_DIR="$HOME/kaine"
DIR="$DEFAULT_DIR"
YES=0
DRY_RUN=0
REPO=""

usage() {
  cat <<'EOF'
Usage: bash scripts/bootstrap.sh [OPTIONS]

Options:
  --dir DIR        target directory (default: $HOME/kaine)
  --repo URL       git repository URL to clone (required when DIR does not exist)
  --yes            run system-package installation commands (without this, they are only printed)
  --dry-run        print every command that would be run and execute nothing
  -h, --help       show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      DIR="$2"
      shift 2
      ;;
    --dir=*)
      DIR="${1#--dir=}"
      shift
      ;;
    --repo)
      REPO="$2"
      shift 2
      ;;
    --repo=*)
      REPO="${1#--repo=}"
      shift
      ;;
    --yes)
      YES=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "bootstrap.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$DRY_RUN" -eq 1 && "$YES" -eq 0 ]]; then
  echo "bootstrap.sh: --dry-run enabled; no commands will be executed" >&2
fi

# --- prerequisites -----------------------------------------------------------

if ! command -v git >/dev/null 2>&1; then
  echo "bootstrap.sh: git is required but not found" >&2
  exit 1
fi

PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "bootstrap.sh: Python >= 3.11 is required but not found" >&2
  exit 1
fi
echo "==> using Python $(command -v "$PYTHON_BIN")"

# --- package manager ---------------------------------------------------------

is_termux=0
if [[ -n "${TERMUX_VERSION:-}" ]] || [[ "${PREFIX:-}" == *com.termux* ]]; then
  is_termux=1
fi

detect_pkg_manager() {
  if [[ "$is_termux" -eq 1 ]] && command -v pkg >/dev/null 2>&1; then
    echo "pkg"
  elif command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  elif command -v brew >/dev/null 2>&1; then
    echo "brew"
  else
    echo "unknown"
  fi
}

PKG_MANAGER=$(detect_pkg_manager)
echo "==> detected package manager: $PKG_MANAGER"

case "$PKG_MANAGER" in
  apt)
    PKGS=(python3 python3-venv python3-dev git build-essential redis-server curl)
    PKG_CMD="sudo apt-get install -y ${PKGS[*]}"
    ;;
  dnf)
    PKGS=(python3 python3-devel git gcc gcc-c++ make redis curl)
    PKG_CMD="sudo dnf install -y ${PKGS[*]}"
    ;;
  pacman)
    PKGS=(python git base-devel redis curl)
    PKG_CMD="sudo pacman -S --needed --noconfirm ${PKGS[*]}"
    ;;
  pkg)
    PKGS=(python git rust binutils redis python-numpy python-cryptography curl)
    PKG_CMD="pkg install -y ${PKGS[*]}"
    ;;
  brew)
    PKGS=(python git redis)
    PKG_CMD="brew install ${PKGS[*]}"
    ;;
  *)
    PKG_CMD=""
    echo "bootstrap.sh: no supported package manager found; install these yourself:" >&2
    echo "    apt : python3 python3-venv python3-dev git build-essential redis-server curl" >&2
    echo "    dnf : python3 python3-devel git gcc gcc-c++ make redis curl" >&2
    echo "    pacman: python git base-devel redis curl" >&2
    echo "    pkg : python git rust binutils redis python-numpy python-cryptography curl" >&2
    echo "    brew: python git redis" >&2
    ;;
esac

if [[ -n "$PKG_CMD" ]]; then
  echo "==> system package command (run only with --yes):"
  echo "    $PKG_CMD"
  if [[ "$YES" -eq 1 || "$DRY_RUN" -eq 1 ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "    [dry-run] would run: $PKG_CMD"
    else
      eval "$PKG_CMD"
    fi
  fi
fi

# --- clone or update ---------------------------------------------------------

if [[ ! -d "$DIR" ]]; then
  if [[ -z "$REPO" ]]; then
    echo "bootstrap.sh: $DIR does not exist; pass --repo <git-url> to clone it" >&2
    echo "    example: bash scripts/bootstrap.sh --repo https://github.com/example/kaine.git --dir $DIR" >&2
    exit 1
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] would clone $REPO into $DIR"
  else
    echo "==> cloning $REPO into $DIR"
    git clone "$REPO" "$DIR"
  fi
else
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] would update $DIR with git pull --ff-only"
  else
    echo "==> updating existing checkout at $DIR"
    git -C "$DIR" pull --ff-only
  fi
fi

# --- install -----------------------------------------------------------------

INSTALL_SH="$DIR/scripts/install.sh"
REDIS_SH="$DIR/scripts/redis-bootstrap.sh"
QDRANT_SH="$DIR/scripts/qdrant-bootstrap.sh"

# A dry run clones nothing, so there is no installer to find yet.
if [[ "$DRY_RUN" -eq 0 && ! -f "$INSTALL_SH" ]]; then
  echo "bootstrap.sh: installer not found at $INSTALL_SH" >&2
  exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "    [dry-run] would run: bash $INSTALL_SH --no-wizard"
else
  echo "==> running installer"
  bash "$INSTALL_SH" --no-wizard
fi

# --- services ----------------------------------------------------------------

# The scripts are run with bash: their file mode does not matter, and a
# missing one is an error, never a silent skip.
for svc_script in "$REDIS_SH" "$QDRANT_SH"; do
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] would run: bash $svc_script"
    continue
  fi
  if [[ ! -f "$svc_script" ]]; then
    echo "bootstrap.sh: service bootstrap not found at $svc_script" >&2
    exit 1
  fi
  echo "==> running $(basename "$svc_script") (Termux skips Qdrant and uses sqlite_vec)"
  bash "$svc_script"
done

# --- wizard ------------------------------------------------------------------

if [[ -t 0 ]]; then
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] would offer to run: python -m kaine.setup"
  else
    echo "==> installation complete; starting first-run setup wizard"
    "$PYTHON_BIN" -m kaine.setup || true
  fi
else
  echo "==> installation complete. Run the wizard interactively with:"
  echo "    cd $DIR && python -m kaine.setup"
fi
