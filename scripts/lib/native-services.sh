#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

# Shared helpers for KAINE service bootstraps (Redis / Qdrant), both
# container and native paths.

# Do not enable set options here: this file is sourced by scripts that already
# run with set -euo pipefail.

# ------------------------------------------------------------------------------
# Qdrant release pin
# ------------------------------------------------------------------------------
QDRANT_VERSION="v1.19.1"
QDRANT_X86_64_URL="https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-gnu.tar.gz"
QDRANT_AARCH64_URL="https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-aarch64-unknown-linux-musl.tar.gz"
QDRANT_PINNED_X86_64_SHA256="eef986e769d4d3e806dd2d546e1b4ecdd416211e54d34b4ed764fac7c58e1085"
QDRANT_PINNED_AARCH64_SHA256="0e607c11705fab22f7d667f4749bc0b6b60a8fa9e91de71880a6ebafbbda1b26"

# ------------------------------------------------------------------------------
# Runtime detection
# ------------------------------------------------------------------------------
docker_available() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Sets RUNTIME_MODE to "native" or "container".  $1 is an explicit choice
# ("native", "container", or "").
detect_runtime_mode() {
  local explicit="$1"
  if [[ "$explicit" == "container" ]]; then
    if ! docker_available; then
      echo "==> --container requested but docker is not available" >&2
      return 1
    fi
    RUNTIME_MODE="container"
  elif [[ "$explicit" == "native" ]]; then
    RUNTIME_MODE="native"
  else
    if docker_available; then
      RUNTIME_MODE="container"
    else
      RUNTIME_MODE="native"
    fi
  fi
}

# Returns "container" if docker is available, otherwise "native".
default_runtime_mode() {
  if docker_available; then
    echo container
  else
    echo native
  fi
}

# ------------------------------------------------------------------------------
# Native process supervisor selection
# ------------------------------------------------------------------------------
# KAINE_SERVICES_SUPERVISOR may be:
#   systemd  - use systemd --user units
#   pidfile  - use a <services dir>/<svc>/<svc>.pid file
#   auto     - systemd if systemctl --user works, otherwise pidfile (default)
detect_supervisor() {
  local explicit="${KAINE_SERVICES_SUPERVISOR:-auto}"
  case "$explicit" in
    systemd)
      SUPERVISOR=systemd
      ;;
    pidfile)
      SUPERVISOR=pidfile
      ;;
    auto)
      if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
        SUPERVISOR=systemd
      else
        SUPERVISOR=pidfile
      fi
      ;;
    *)
      echo "==> unknown KAINE_SERVICES_SUPERVISOR=${explicit}; falling back to pidfile" >&2
      SUPERVISOR=pidfile
      ;;
  esac
}

using_systemd() {
  [[ "${SUPERVISOR:-}" == "systemd" ]]
}

# Resolve once when this library is sourced.  Callers may override by setting
# KAINE_SERVICES_SUPERVISOR before sourcing.
detect_supervisor

# ------------------------------------------------------------------------------
# Credential handling (shared by both container and native paths)
# ------------------------------------------------------------------------------
# Usage: resolve_credential <env_key> <section> <secret_key> <rotate> <keep> <out_var>
resolve_credential() {
  local env_key="$1"
  local section="$2"
  local secret_key="$3"
  local rotate="$4"
  local keep="$5"
  local -n __out="$6"
  __out=""

  local existing=""
  if [[ "$rotate" -eq 0 && -f "$ENV_FILE" ]]; then
    existing=$(grep -E "^${env_key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
    existing=${existing%$'\r'}
    local unusable=0
    if [[ -z "$existing" || "${#existing}" -lt 32 ]]; then
      unusable=1
    else
      shopt -s nocasematch
      if [[ "$existing" == replace-me* ]]; then
        unusable=1
      fi
      shopt -u nocasematch
    fi
    if [[ "$unusable" -eq 1 ]]; then
      if [[ "$keep" -eq 1 ]]; then
        echo "==> keeping credential requested but no usable existing ${env_key}; generating new" >&2
      fi
      if [[ -n "$existing" ]]; then
        echo "==> existing ${env_key} is shorter than 32 characters or a placeholder; generating a new one" >&2
      fi
    else
      echo "==> kept the existing ${env_key} from ${ENV_FILE}; pass --rotate to replace it"
      __out="$existing"
      return 0
    fi
  fi
  __out=$(openssl rand -hex 32)
  echo "==> generated a fresh random ${env_key}"
}

write_env_credential() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local py="$4"
  umask 077
  printf '%s\n' "$value" | "$py" -m kaine.secrets_file env "$env_file" "$key" -
  chmod 600 "$env_file"
  echo "==> wrote ${env_file} with ${key} (mode 600)"
}

mirror_toml_credential() {
  local secrets_file="$1"
  local example_file="$2"
  local section="$3"
  local key="$4"
  local value="$5"
  local py="$6"
  if [[ ! -f "$secrets_file" ]]; then
    cp "$example_file" "$secrets_file"
    echo "==> created ${secrets_file} from example"
  fi
  chmod 600 "$secrets_file"
  printf '%s\n' "$value" | "$py" -m kaine.secrets_file toml "$secrets_file" "$section" "$key" -
  echo "==> mirrored ${key} into ${secrets_file}"
}

# ------------------------------------------------------------------------------
# Health checks
# ------------------------------------------------------------------------------
wait_redis_ping() {
  local pw="$1"
  local host="${2:-127.0.0.1}"
  local port="${3:-6479}"
  local max="${4:-30}"
  echo -n "==> waiting for redis at ${host}:${port}"
  local i
  for i in $(seq 1 "$max"); do
    if REDISCLI_AUTH="$pw" redis-cli -h "$host" -p "$port" --no-auth-warning ping 2>/dev/null | grep -q PONG; then
      echo " ok"
      return 0
    fi
    echo -n "."
    sleep 0.5
    if [[ "$i" -eq "$max" ]]; then
      echo
      echo "==> timed out waiting for PONG" >&2
      return 1
    fi
  done
}

wait_qdrant_readyz() {
  local key="$1"
  local host="${2:-127.0.0.1}"
  local port="${3:-6533}"
  local max="${4:-60}"
  echo -n "==> waiting for qdrant /readyz at ${host}:${port}"
  local i
  for i in $(seq 1 "$max"); do
    if printf 'api-key: %s\n' "$key" | curl -fsS -H @- "http://${host}:${port}/readyz" >/dev/null 2>&1; then
      echo " ok"
      return 0
    fi
    echo -n "."
    sleep 0.5
    if [[ "$i" -eq "$max" ]]; then
      echo
      echo "==> timed out waiting for /readyz" >&2
      return 1
    fi
  done
}

# ------------------------------------------------------------------------------
# Platform helpers
# ------------------------------------------------------------------------------
is_termux() {
  [[ -n "${TERMUX_VERSION:-}" ]] || [[ "${PREFIX:-}" == *com.termux* ]]
}

detect_qdrant_arch() {
  local arch
  arch=$(uname -m)
  case "$arch" in
    x86_64)
      echo x86_64
      ;;
    aarch64|arm64)
      echo aarch64
      ;;
    *)
      echo "==> unsupported Qdrant architecture: ${arch}" >&2
      return 1
      ;;
  esac
}

# ------------------------------------------------------------------------------
# Native service data directory
# ------------------------------------------------------------------------------
# The directory that holds native service data: <data root>/state/services
# when [storage].data_root (or KAINE_DATA_ROOT) is set, else under the checkout.
kaine_services_dir() {
  local py="${PY:-$ROOT/.venv/bin/python}"
  [[ -x "$py" ]] || py=python3
  local root
  root="$(cd "$ROOT" && "$py" -m kaine.setup.data_root root 2>/dev/null || true)"
  [[ -n "$root" ]] || root="$ROOT"
  printf '%s/state/services\n' "$root"
}

# ------------------------------------------------------------------------------
# Native process identity check
# ------------------------------------------------------------------------------
# Verify that a pid actually belongs to the expected KAINE service binary.
# A live but unrelated pid (PID reuse) must never be trusted.
native_pid_is_ours() {
  local svc="$1"
  local pid="$2"
  local expected=""

  case "$svc" in
    redis)
      expected="redis-server"
      ;;
    qdrant)
      expected="$(kaine_services_dir)/qdrant/bin/qdrant"
      ;;
    *)
      return 1
      ;;
  esac

  local cmdline=""
  if [[ -r "/proc/$pid/cmdline" ]]; then
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
  fi
  if [[ -z "$cmdline" ]]; then
    cmdline=$(ps -o args= -p "$pid" 2>/dev/null || true)
  fi

  if [[ -n "$cmdline" && "$cmdline" == *"$expected"* ]]; then
    return 0
  fi
  return 1
}

# ------------------------------------------------------------------------------
# Native process supervision helpers
# ------------------------------------------------------------------------------
native_is_running() {
  local svc="$1"
  if using_systemd; then
    if systemctl --user is-active "kaine-${svc}.service" >/dev/null 2>&1; then
      return 0
    fi
  fi
  local pidfile="$(kaine_services_dir)/${svc}/${svc}.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if native_pid_is_ours "$svc" "$pid"; then
        return 0
      fi
      echo "==> removing stale pidfile for kaine-${svc} (pid ${pid} is not ours)" >&2
      rm -f "$pidfile"
    fi
  fi
  return 1
}

container_is_running() {
  local svc="$1"
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  # Capture the list first: piping into `grep -q` under pipefail can report a
  # running container as absent (grep exits early, docker gets SIGPIPE).
  local names
  names=$(docker ps --format '{{.Names}}' 2>/dev/null) || return 1
  if grep -qx "kaine-${svc}" <<<"$names"; then
    return 0
  fi
  return 1
}

native_stop_service() {
  local svc="$1"
  if using_systemd; then
    systemctl --user stop "kaine-${svc}.service" >/dev/null 2>&1 || true
  fi
  local pidfile="$(kaine_services_dir)/${svc}/${svc}.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      if native_pid_is_ours "$svc" "$pid"; then
        kill "$pid" || true
        local i
        for i in $(seq 1 20); do
          if ! kill -0 "$pid" 2>/dev/null; then break; fi
          sleep 0.2
        done
      else
        echo "==> stale pidfile for kaine-${svc} (pid ${pid} is not ours); not signalling it" >&2
      fi
    fi
    rm -f "$pidfile"
  fi
}

# ------------------------------------------------------------------------------
# Native Redis bootstrap
# ------------------------------------------------------------------------------
# Usage: env_file_value <file> <key>
# Prints the last value of <key> in a compose-style .env file, or nothing.
# Accepts what docker compose accepts for these lines: leading spaces, an
# "export " prefix, one pair of surrounding single or double quotes, and an
# unquoted " # comment" after the value. <key> must be [A-Za-z_][A-Za-z0-9_]*.
env_file_value() {
  local file="$1" key="$2" line value="" found=0
  [[ -f "$file" ]] || return 0
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=(.*)$ ]]; then
      value=${BASH_REMATCH[2]}
      found=1
    fi
  done < "$file"
  [[ "$found" -eq 1 ]] || return 0
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ ${#value} -ge 2 && ( ( "${value:0:1}" == '"' && "${value: -1}" == '"' ) || ( "${value:0:1}" == "'" && "${value: -1}" == "'" ) ) ]]; then
    value=${value:1:${#value}-2}
  else
    value=${value%%[[:space:]]#*}
    value="${value%"${value##*[![:space:]]}"}"
  fi
  printf '%s' "$value"
}

native_bootstrap_redis() {
  local root="$1"
  local pw="$2"
  local rotate="${3:-0}"
  local svc_dir="$(kaine_services_dir)/redis"
  local data_dir="$svc_dir/data"
  local logs_dir="$svc_dir/logs"
  local conf="$svc_dir/redis.conf"
  local pidfile="$svc_dir/redis.pid"
  # Memory ceiling: KAINE_REDIS_MAXMEMORY from the environment, else from
  # compose/.env (the variable the container path reads), else 4gb.
  # noeviction stays: the bus fails loud rather than dropping events.
  local maxmemory="${KAINE_REDIS_MAXMEMORY:-}"
  if [[ -z "$maxmemory" && -f "$root/compose/.env" ]]; then
    maxmemory=$(env_file_value "$root/compose/.env" KAINE_REDIS_MAXMEMORY)
  fi
  maxmemory="${maxmemory:-4gb}"
  if [[ ! "$maxmemory" =~ ^[0-9]+([kKmMgG][bB]?)?$ ]]; then
    echo "==> KAINE_REDIS_MAXMEMORY must be a Redis memory size such as 4gb or 12gb" >&2
    return 1
  fi

  if ! command -v redis-server >/dev/null 2>&1; then
    if is_termux; then
      echo "==> redis-server not found on PATH. Install it with: pkg install redis" >&2
    else
      echo "==> redis-server not found on PATH" >&2
    fi
    return 1
  fi

  mkdir -p "$data_dir" "$logs_dir"

  cat > "$conf" <<EOF
port 6479
bind 127.0.0.1
requirepass $pw
appendonly yes
appendfsync everysec
dir $data_dir
pidfile $pidfile
logfile $logs_dir/redis.log
daemonize no
maxmemory $maxmemory
maxmemory-policy noeviction
protected-mode yes
save ""
EOF
  chmod 600 "$conf"
  echo "==> wrote ${conf} (mode 600)"

  if using_systemd; then
    local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    local unit="$unit_dir/kaine-redis.service"
    cat > "$unit" <<EOF
[Unit]
Description=KAINE Redis bus (native)
After=network.target

[Service]
Type=simple
ExecStart=$(command -v redis-server) $conf
WorkingDirectory=$root
Restart=on-failure
PIDFile=$pidfile

[Install]
WantedBy=default.target
EOF
    chmod 600 "$unit"
    echo "==> wrote user systemd unit ${unit}"
    systemctl --user daemon-reload
    systemctl --user enable kaine-redis.service
    systemctl --user restart kaine-redis.service || systemctl --user start kaine-redis.service
    return 0
  fi

  # Non-systemd: supervised background process with a pid file.
  if [[ -f "$pidfile" ]]; then
    local oldpid
    oldpid=$(cat "$pidfile")
    if [[ -n "$oldpid" ]] && kill -0 "$oldpid" 2>/dev/null; then
      if ! native_pid_is_ours redis "$oldpid"; then
        echo "==> stale pidfile for kaine-redis (pid ${oldpid}); starting fresh"
      elif [[ "$rotate" -eq 0 ]]; then
        echo "==> kaine-redis already running (pid ${oldpid}); not starting a second copy"
        return 0
      else
        echo "==> stopping existing kaine-redis (pid ${oldpid}) for rotation"
        kill "$oldpid" || true
        local i
        for i in $(seq 1 20); do
          if ! kill -0 "$oldpid" 2>/dev/null; then break; fi
          sleep 0.2
        done
      fi
    fi
    rm -f "$pidfile"
  fi

  nohup redis-server "$conf" > "$logs_dir/redis.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo "==> started kaine-redis in the background (pid ${pid})"
}

# ------------------------------------------------------------------------------
# Native Qdrant bootstrap
# ------------------------------------------------------------------------------
native_bootstrap_qdrant() {
  local root="$1"
  local key="$2"
  local rotate="${3:-0}"

  if is_termux; then
    echo "==> Qdrant has no Android build. On Termux use [mnemos].backend = \"sqlite_vec\" (phase 3)."
    return 0
  fi

  local arch
  arch=$(detect_qdrant_arch)
  local url sha
  if [[ "$arch" == "x86_64" ]]; then
    url="$QDRANT_X86_64_URL"
    sha="${QDRANT_X86_64_SHA256:-$QDRANT_PINNED_X86_64_SHA256}"
  else
    url="$QDRANT_AARCH64_URL"
    sha="${QDRANT_AARCH64_SHA256:-$QDRANT_PINNED_AARCH64_SHA256}"
  fi

  local svc_dir="$(kaine_services_dir)/qdrant"
  local bin_dir="$svc_dir/bin"
  local tmp="$svc_dir/qdrant.tar.gz"
  local binary="$bin_dir/qdrant"
  local pidfile="$svc_dir/qdrant.pid"
  local env_file="$svc_dir/qdrant.env"
  mkdir -p "$bin_dir" "$svc_dir/storage" "$svc_dir/snapshots"

  if [[ "$rotate" -eq 0 ]] && native_is_running qdrant; then
    echo "==> kaine-qdrant already running; not starting a second copy"
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "==> curl not found on PATH; needed to download the Qdrant binary" >&2
    return 1
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "==> tar not found on PATH" >&2
    return 1
  fi
  if ! command -v sha256sum >/dev/null 2>&1; then
    echo "==> sha256sum not found on PATH" >&2
    return 1
  fi

  # KAINE_QDRANT_ARCHIVE: a pre-downloaded release archive for an offline or
  # air-gapped host. It is checked against the same pinned sha256 below.
  if [[ -n "${KAINE_QDRANT_ARCHIVE:-}" ]]; then
    if [[ ! -f "$KAINE_QDRANT_ARCHIVE" ]]; then
      echo "==> KAINE_QDRANT_ARCHIVE=${KAINE_QDRANT_ARCHIVE} is not a file" >&2
      return 1
    fi
    echo "==> using the local Qdrant archive ${KAINE_QDRANT_ARCHIVE}"
    cp "$KAINE_QDRANT_ARCHIVE" "$tmp"
  else
    echo "==> downloading Qdrant ${QDRANT_VERSION} (${arch}) from ${url}"
    curl -fsSL "$url" -o "$tmp"
  fi

  echo "==> verifying Qdrant archive checksum"
  if ! printf '%s  %s\n' "$sha" "$tmp" | sha256sum -c -; then
    rm -f "$tmp"
    rm -rf "$bin_dir"
    echo "==> Qdrant archive sha256 mismatch; refusing to start" >&2
    return 1
  fi

  echo "==> extracting Qdrant binary to ${bin_dir}"
  tar --no-same-owner -xzf "$tmp" -C "$bin_dir" qdrant
  chmod +x "$binary"
  rm -f "$tmp"

  cat > "$env_file" <<EOF
QDRANT__SERVICE__HTTP_PORT=6533
QDRANT__SERVICE__GRPC_PORT=6534
QDRANT__SERVICE__HOST=127.0.0.1
QDRANT__SERVICE__API_KEY=$key
QDRANT__STORAGE__STORAGE_PATH=${svc_dir}/storage
QDRANT__STORAGE__SNAPSHOTS_PATH=${svc_dir}/snapshots
QDRANT__TELEMETRY_DISABLED=true
EOF
  chmod 600 "$env_file"

  if [[ "$rotate" -eq 1 ]] && native_is_running qdrant; then
    echo "==> rotating API key; stopping existing kaine-qdrant"
    native_stop_service qdrant
  fi

  if using_systemd; then
    local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    local unit="$unit_dir/kaine-qdrant.service"
    cat > "$unit" <<EOF
[Unit]
Description=KAINE Qdrant memory store (native)
After=network.target

[Service]
Type=simple
WorkingDirectory=$root
EnvironmentFile=$env_file
ExecStart=$binary
Restart=on-failure
PIDFile=$pidfile

[Install]
WantedBy=default.target
EOF
    chmod 600 "$unit"
    echo "==> wrote user systemd unit ${unit}"
    systemctl --user daemon-reload
    systemctl --user enable kaine-qdrant.service
    systemctl --user restart kaine-qdrant.service || systemctl --user start kaine-qdrant.service
    return 0
  fi

  # Non-systemd: load the env file in a subshell so the API key is never on argv.
  ( set -a; . "$env_file"; set +a; exec nohup "$binary" ) > "$svc_dir/qdrant.log" 2>&1 &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo "==> started kaine-qdrant in the background (pid ${pid})"
}

# ------------------------------------------------------------------------------
# scripts/services.sh helpers
# ------------------------------------------------------------------------------
service_current_mode() {
  local svc="$1"
  # This checkout's own native service first: a shared container elsewhere on
  # the host must never be mistaken for what this checkout runs.
  if native_is_running "$svc"; then
    echo native
    return 0
  fi
  if container_is_running "$svc"; then
    echo container
    return 0
  fi
  echo none
  return 0
}

service_status() {
  local svc="$1"
  local mode
  mode=$(service_current_mode "$svc")
  case "$mode" in
    container)
      echo "kaine-${svc}: container (running)"
      ;;
    native)
      echo "kaine-${svc}: native (running)"
      ;;
    none)
      echo "kaine-${svc}: not running"
      ;;
  esac
}

service_start() {
  local svc="$1"
  local mode
  mode=$(service_current_mode "$svc")
  if [[ "$mode" != "none" ]]; then
    echo "kaine-${svc} already running (${mode}); refusing to start a second copy" >&2
    return 1
  fi
  local desired
  desired=$(default_runtime_mode)
  if [[ "$desired" == "container" ]]; then
    echo "==> starting kaine-${svc} (container)"
    "$ROOT/scripts/${svc}-bootstrap.sh"
  else
    echo "==> starting kaine-${svc} (native)"
    "$ROOT/scripts/${svc}-bootstrap.sh" --native
  fi
}

service_stop() {
  local svc="$1"
  local mode
  mode=$(service_current_mode "$svc")
  case "$mode" in
    container)
      # The containers have fixed names, so every KAINE checkout on this host
      # sees the same ones, and the running entity's bus or memory may live in
      # them. Stopping one therefore needs an explicit --container, and it is
      # stopped, never removed.
      if [[ "${KAINE_SERVICES_CONTAINER_OK:-0}" != "1" ]]; then
        echo "kaine-${svc} runs as a shared container; it may hold a running entity's state." >&2
        echo "Re-run with --container to stop it." >&2
        return 1
      fi
      echo "==> stopping kaine-${svc} (container)"
      if ! docker compose -f "compose/${svc}.yml" stop 2>&1 | sed 's/^/    /'; then
        echo "==> docker compose stop failed for kaine-${svc}" >&2
        return 1
      fi
      if container_is_running "$svc"; then
        echo "==> kaine-${svc} container is still running after stop" >&2
        return 1
      fi
      ;;
    native)
      echo "==> stopping kaine-${svc} (native)"
      native_stop_service "$svc"
      ;;
    none)
      echo "kaine-${svc} is not running"
      ;;
  esac
}
