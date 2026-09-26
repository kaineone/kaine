# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import hashlib
import io
import os
import platform
import shutil
import signal
import stat
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REAL_HOME = Path.home()
REAL_SYSTEMD_USER = REAL_HOME / ".config" / "systemd" / "user"

# System tools that the scripts invoke by name.  They are symlinked into a
# temporary sysbin directory so the hermetic PATH never includes /usr/bin or
# /bin wholesale (the real docker lives in /usr/bin on many machines).
SYSTEM_TOOLS = [
    "bash", "env", "sed", "grep", "awk", "cat", "mkdir", "chmod", "rm", "mv",
    "cp", "tar", "gzip", "sha256sum", "sleep", "kill", "date", "dirname",
    "basename", "head", "tail", "tr", "cut", "mktemp", "openssl", "python3",
    "id", "printf", "test", "touch", "ln", "readlink", "uname", "ps", "nohup",
    "seq",
]

# Stubs that are present in the stub directory for every invocation.  They are
# safe-by-default: they never touch the developer's machine.  Tests can remove
# a stub (omit_stubs) to simulate "command not found", or replace one
# (extra_stubs) to inject behaviour.
REQUIRED_STUBS = [
    "systemctl", "docker", "sudo", "loginctl", "redis-server", "redis-cli",
    "curl", "qdrant",
]


def _find_system_tool(name):
    for d in ("/usr/bin", "/bin", "/usr/local/bin"):
        p = Path(d) / name
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise RuntimeError(f"required system tool not found: {name}")


@pytest.fixture(autouse=True)
def guard_real_systemd():
    """Fail any test that leaves a real user systemd unit behind."""
    before = set(REAL_SYSTEMD_USER.glob("kaine-*.service")) if REAL_SYSTEMD_USER.exists() else set()
    yield
    after = set(REAL_SYSTEMD_USER.glob("kaine-*.service")) if REAL_SYSTEMD_USER.exists() else set()
    leaked = after - before
    if leaked:
        for p in leaked:
            try:
                p.unlink()
            except Exception:
                pass
        pytest.fail(f"test touched real systemd user units: {leaked}")


class _RepoRoot(type(Path())):
    """The fake repo's path, carrying where its home, sysbin and stubs live."""


@pytest.fixture
def fake_repo(tmp_path, request):
    root = _RepoRoot(tmp_path / "repo")
    home = tmp_path / "home"
    sysbin = tmp_path / "sysbin"
    stubs = root / "bin"
    xdg_config = home / ".config"
    for d in [
        root / "scripts",
        root / "scripts/lib",
        root / "kaine",
        root / "compose",
        root / "config",
        stubs,
        sysbin,
        xdg_config,
    ]:
        d.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)

    # Copy the scripts under test.
    shutil.copy2(REPO / "scripts" / "redis-bootstrap.sh", root / "scripts" / "redis-bootstrap.sh")
    shutil.copy2(REPO / "scripts" / "qdrant-bootstrap.sh", root / "scripts" / "qdrant-bootstrap.sh")
    shutil.copy2(REPO / "scripts" / "services.sh", root / "scripts" / "services.sh")
    shutil.copy2(
        REPO / "scripts" / "lib" / "native-services.sh",
        root / "scripts" / "lib" / "native-services.sh",
    )

    # Minimal kaine package so `python3 -m kaine.secrets_file` works.
    for name in ("__init__.py", "hardware.py", "secrets_file.py"):
        shutil.copy2(REPO / "kaine" / name, root / "kaine" / name)

    shutil.copy2(REPO / "config" / "secrets.example.toml", root / "config" / "secrets.example.toml")

    # Symlink required system tools into sysbin.
    for tool in SYSTEM_TOOLS:
        src = _find_system_tool(tool)
        dst = sysbin / tool
        if not dst.exists():
            dst.symlink_to(src)

    # Default stubs: safe (do not touch the host).
    for name in REQUIRED_STUBS:
        path = stubs / name
        path.write_text("#!/bin/sh\nexit 1\n")
        path.chmod(0o755)

    # redis-server stub: record args and stay alive so a pid file is meaningful.
    args_log = root / "redis-server-args.log"
    (stubs / "redis-server").write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "$@" >> {args_log!s}\n'
        'while true; do sleep 1; done\n'
    )
    (stubs / "redis-server").chmod(0o755)

    # redis-cli answers PONG.
    (stubs / "redis-cli").write_text("#!/bin/sh\necho PONG\n")
    (stubs / "redis-cli").chmod(0o755)

    # sleep exits immediately to keep tests fast.
    (stubs / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (stubs / "sleep").chmod(0o755)

    # Default qdrant download fixture: a tarball containing a do-nothing qdrant.
    qdrant_script = b"#!/bin/sh\nwhile true; do sleep 1; done\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="qdrant")
        info.size = len(qdrant_script)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(qdrant_script))
    fixture_path = root / "qdrant-fixture.tar.gz"
    fixture_path.write_bytes(buf.getvalue())

    # Default curl stub serves the default fixture and answers /readyz.
    curl_stub = (
        "#!/usr/bin/env python3\n"
        "import shutil, sys\n"
        f"FIXTURE = {str(fixture_path)!r}\n"
        "args = sys.argv[1:]\n"
        "out = None\n"
        "url = None\n"
        "skip = False\n"
        "for i, a in enumerate(args):\n"
        "    if skip:\n"
        "        skip = False\n"
        "        continue\n"
        "    if a == '-o':\n"
        "        out = args[i + 1]\n"
        "        skip = True\n"
        "    elif a.startswith('-'):\n"
        "        continue\n"
        "    else:\n"
        "        url = a\n"
        "if out is None:\n"
        "    out = '/dev/null'\n"
        "if url and '.tar.gz' in url:\n"
        "    shutil.copy(FIXTURE, out)\n"
        "elif url and '/readyz' in url:\n"
        "    print('all shards are ready')\n"
        "sys.exit(0)\n"
    )
    (stubs / "curl").write_text(curl_stub)
    (stubs / "curl").chmod(0o755)

    # Make the root object self-describing so _run knows where home/sysbin/stubs are.
    root.home = home
    root.sysbin = sysbin
    root.stubs = stubs

    def cleanup():
        for svc in ("redis", "qdrant"):
            pidfile = root / "state" / "services" / svc / f"{svc}.pid"
            if pidfile.exists():
                try:
                    pid = int(pidfile.read_text().strip().split()[0])
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass

    request.addfinalizer(cleanup)
    return root


def _run(
    root,
    name,
    *flags,
    exclude_docker=False,
    extra_env=None,
    env=None,
    omit_stubs=None,
    extra_stubs=None,
):
    """
    Run a bootstrap/service script in a completely fresh, hermetic environment.

    The real developer HOME is never placed on PATH or in the env.  Stubs are
    copied into a per-invocation directory so a test can remove or replace
    individual commands to simulate absence or inject behaviour.
    """
    if extra_env is not None:
        if env is None:
            env = extra_env
        else:
            env = {**extra_env, **env}
    env = dict(env or {})

    assert str(root.home) != str(REAL_HOME), "real HOME leaked into test env"
    if "PATH" in env:
        raise ValueError("do not override PATH in _run; use omit_stubs/extra_stubs")

    omit = set(omit_stubs or [])
    if exclude_docker:
        omit.add("docker")

    # Build a per-invocation stub directory from the fixture defaults.
    run_stubs = root / "bin-run"
    if run_stubs.exists():
        shutil.rmtree(run_stubs)
    run_stubs.mkdir()
    for src in root.stubs.iterdir():
        dst = run_stubs / src.name
        shutil.copy2(src, dst)
        dst.chmod(0o755)
    for s in omit:
        (run_stubs / s).unlink(missing_ok=True)
    for s, content in (extra_stubs or {}).items():
        dst = run_stubs / s
        dst.write_text(content)
        dst.chmod(0o755)

    path = f"{run_stubs}:{root.sysbin}"

    run_env = {
        "HOME": str(root.home),
        "XDG_CONFIG_HOME": str(root.home / ".config"),
        "PATH": path,
        "TERM": "xterm-256color",
        "LANG": "C",
        "PWD": str(root),
    }
    run_env.update(env)

    for k, v in run_env.items():
        assert str(REAL_HOME) not in str(v), f"real HOME leaked in env {k}={v}"

    # Make the default qdrant fixture pass its own sha256 check on native runs.
    fixture = root / "qdrant-fixture.tar.gz"
    if fixture.exists():
        h = hashlib.sha256(fixture.read_bytes()).hexdigest()
        run_env.setdefault("QDRANT_X86_64_SHA256", h)
        run_env.setdefault("QDRANT_AARCH64_SHA256", h)

    return subprocess.run(
        ["bash", str(root / "scripts" / name), *flags],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(root),
    )


def _parse_env(path):
    values = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _load_toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _qdrant_curl_stub(root, fixture, readyz_response="all shards are ready"):
    text = (
        "#!/usr/bin/env python3\n"
        "import shutil, sys\n"
        f"FIXTURE = {str(fixture)!r}\n"
        f"READYZ = {readyz_response!r}\n"
        "args = sys.argv[1:]\n"
        "out = None\n"
        "url = None\n"
        "skip = False\n"
        "for i, a in enumerate(args):\n"
        "    if skip:\n"
        "        skip = False\n"
        "        continue\n"
        "    if a == '-o':\n"
        "        out = args[i + 1]\n"
        "        skip = True\n"
        "    elif a.startswith('-'):\n"
        "        continue\n"
        "    else:\n"
        "        url = a\n"
        "if out is None:\n"
        "    out = '/dev/null'\n"
        "if url and '.tar.gz' in url:\n"
        "    shutil.copy(FIXTURE, out)\n"
        "elif url and '/readyz' in url:\n"
        "    print(READYZ)\n"
        "sys.exit(0)\n"
    )
    path = root / "bin" / "curl"
    path.write_text(text)
    path.chmod(0o755)


def _qdrant_fixture_hash(root, fixture):
    return hashlib.sha256(fixture.read_bytes()).hexdigest()


def _qdrant_sha_env(root, fixture):
    machine = platform.machine()
    if machine in ("aarch64", "arm64"):
        return {"QDRANT_AARCH64_SHA256": _qdrant_fixture_hash(root, fixture)}
    elif machine in ("x86_64", "AMD64"):
        return {"QDRANT_X86_64_SHA256": _qdrant_fixture_hash(root, fixture)}
    pytest.skip(f"unsupported test architecture: {machine}")


def test_redis_fresh(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0

    env = _parse_env(fake_repo / "compose" / ".env")
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    pw = env["KAINE_REDIS_PASSWORD"]

    assert secrets["redis"]["password"] == pw
    assert len(pw) == 64
    assert all(c in "0123456789abcdef" for c in pw)
    assert stat.S_IMODE((fake_repo / "compose" / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((fake_repo / "config" / "secrets.toml").stat().st_mode) == 0o600
    assert pw not in r.stdout and pw not in r.stderr


def test_qdrant_then_redis_keeps_key(fake_repo):
    rq = _run(fake_repo, "qdrant-bootstrap.sh")
    assert rq.returncode == 0

    env1 = _parse_env(fake_repo / "compose" / ".env")
    key1 = env1["KAINE_QDRANT_API_KEY"]
    secrets1 = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets1["qdrant"]["api_key"] == key1
    assert key1 not in rq.stdout and key1 not in rq.stderr

    rr = _run(fake_repo, "redis-bootstrap.sh")
    assert rr.returncode == 0

    env2 = _parse_env(fake_repo / "compose" / ".env")
    assert env2["KAINE_QDRANT_API_KEY"] == key1
    secrets2 = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets2["qdrant"]["api_key"] == key1


def test_redis_idempotence_and_rotate(fake_repo):
    _run(fake_repo, "redis-bootstrap.sh")
    pw = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]

    _run(fake_repo, "redis-bootstrap.sh")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"] == pw

    _run(fake_repo, "redis-bootstrap.sh", "--keep-password")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"] == pw

    r = _run(fake_repo, "redis-bootstrap.sh", "--rotate")
    new_pw = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert new_pw != pw
    assert secrets["redis"]["password"] == new_pw
    assert new_pw not in r.stdout and new_pw not in r.stderr


def test_qdrant_idempotence_and_rotate(fake_repo):
    _run(fake_repo, "qdrant-bootstrap.sh")
    key = _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"]

    _run(fake_repo, "qdrant-bootstrap.sh")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"] == key

    _run(fake_repo, "qdrant-bootstrap.sh", "--keep-key")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"] == key

    r = _run(fake_repo, "qdrant-bootstrap.sh", "--rotate")
    new_key = _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"]
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert new_key != key
    assert secrets["qdrant"]["api_key"] == new_key
    assert new_key not in r.stdout and new_key not in r.stderr


def test_redis_preserves_other_table_password(fake_repo):
    secrets_path = fake_repo / "config" / "secrets.toml"
    secrets_path.write_text(
        '[other]\npassword = "keep-me"\n\n[redis]\npassword = "placeholder-to-be-replaced"\n',
        encoding="utf-8",
    )

    _run(fake_repo, "redis-bootstrap.sh")

    secrets = _load_toml(secrets_path)
    assert secrets["other"]["password"] == "keep-me"
    assert secrets["redis"]["password"] != "placeholder-to-be-replaced"


def test_no_secret_in_output(fake_repo):
    r_redis = _run(fake_repo, "redis-bootstrap.sh")
    r_qdrant = _run(fake_repo, "qdrant-bootstrap.sh")

    env = _parse_env(fake_repo / "compose" / ".env")
    pw = env["KAINE_REDIS_PASSWORD"]
    key = env["KAINE_QDRANT_API_KEY"]

    combined = r_redis.stdout + r_redis.stderr + r_qdrant.stdout + r_qdrant.stderr
    assert pw not in combined
    assert key not in combined


@pytest.mark.parametrize("name", ["redis-bootstrap.sh", "qdrant-bootstrap.sh"])
def test_help(name, fake_repo):
    r = _run(fake_repo, name, "--help")
    assert r.returncode == 0
    assert "--rotate" in r.stdout
    assert not any(line.startswith("set -") for line in r.stdout.splitlines())


@pytest.mark.parametrize("name", ["redis-bootstrap.sh", "qdrant-bootstrap.sh"])
def test_unknown_flag(name, fake_repo):
    r = _run(fake_repo, name, "--bogus")
    assert r.returncode == 2


def test_redis_weak_existing_password_is_regenerated(fake_repo):
    env_path = fake_repo / "compose" / ".env"
    env_path.write_text("KAINE_REDIS_PASSWORD=zq9weak\n")
    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0

    env = _parse_env(env_path)
    pw = env["KAINE_REDIS_PASSWORD"]
    assert pw != "zq9weak"
    assert len(pw) == 64
    assert all(c in "0123456789abcdef" for c in pw)
    assert "zq9weak" not in r.stdout and "zq9weak" not in r.stderr
    assert "shorter than 32" in (r.stdout + r.stderr).lower()

    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets["redis"]["password"] == pw


def test_redis_placeholder_password_is_regenerated(fake_repo):
    env_path = fake_repo / "compose" / ".env"
    env_path.write_text("KAINE_REDIS_PASSWORD=REPLACE-ME-WITH-THE-PASSWORD-IN-compose-env\n")
    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0

    env = _parse_env(env_path)
    pw = env["KAINE_REDIS_PASSWORD"]
    assert pw != "REPLACE-ME-WITH-THE-PASSWORD-IN-compose-env"
    assert len(pw) == 64

    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets["redis"]["password"] == pw


def test_crlf_env_keeps_same_password_everywhere(fake_repo):
    env_path = fake_repo / "compose" / ".env"
    env_path.write_bytes(b"KAINE_REDIS_PASSWORD=" + b"a" * 64 + b"\r\n")
    import shlex

    seen = fake_repo / "auth.log"
    stub = fake_repo / "bin" / "redis-cli"
    stub.write_text(
        f"#!/bin/sh\nprintf '%s' \"$REDISCLI_AUTH\" > {shlex.quote(str(seen))}\necho PONG\n"
    )
    stub.chmod(0o755)
    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0

    env = _parse_env(env_path)
    pw = env["KAINE_REDIS_PASSWORD"]
    assert pw == "a" * 64

    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets["redis"]["password"] == "a" * 64
    assert "pass --rotate" in r.stdout
    assert seen.read_bytes() == b"a" * 64


def test_credentials_not_in_stub_argv(fake_repo):
    import shlex

    argv_log = fake_repo / "argv.log"

    redis_stub = fake_repo / "bin" / "redis-cli"
    redis_stub.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {shlex.quote(str(argv_log))}\necho PONG\n"
    )
    redis_stub.chmod(0o755)

    curl_stub = fake_repo / "bin" / "curl"
    curl_stub.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {shlex.quote(str(argv_log))}\nexit 0\n"
    )
    curl_stub.chmod(0o755)

    # The container path: the one whose CLI calls this test inspects.
    docker = "#!/bin/sh\n[ \"$1\" = \"compose\" ] && exit 0\n[ \"$1\" = \"ps\" ] && exit 0\nexit 1\n"
    rr = _run(fake_repo, "redis-bootstrap.sh", "--container", extra_stubs={"docker": docker})
    assert rr.returncode == 0, rr.stdout + rr.stderr

    rq = _run(fake_repo, "qdrant-bootstrap.sh", "--container", extra_stubs={"docker": docker})
    assert rq.returncode == 0, rq.stdout + rq.stderr

    env = _parse_env(fake_repo / "compose" / ".env")
    pw = env["KAINE_REDIS_PASSWORD"]
    key = env["KAINE_QDRANT_API_KEY"]

    log = argv_log.read_text()
    assert pw not in log
    assert key not in log


def test_scripts_prefer_venv_python(fake_repo):
    import shlex
    import sys

    venv_bin = fake_repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    py_log = fake_repo / "py.log"
    real_python = sys.executable

    venv_python = venv_bin / "python"
    venv_python.write_text(
        f"#!/bin/sh\nprintf 'venv-python\\n' >> {shlex.quote(str(py_log))}\n"
        f"exec {shlex.quote(real_python)} \"$@\"\n"
    )
    venv_python.chmod(0o755)

    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0
    assert "venv-python" in py_log.read_text()


# ------------------------------------------------------------------------------
# Native-services tests
# ------------------------------------------------------------------------------


def test_native_redis_config_and_password_reuse(fake_repo):
    r1 = _run(fake_repo, "redis-bootstrap.sh")
    assert r1.returncode == 0
    pw = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]

    r2 = _run(fake_repo, "redis-bootstrap.sh", "--native")
    assert r2.returncode == 0

    conf = (fake_repo / "state" / "services" / "redis" / "redis.conf").read_text()
    assert "port 6479" in conf
    assert "bind 127.0.0.1" in conf
    assert f"requirepass {pw}" in conf
    assert "appendonly yes" in conf
    assert "appendfsync everysec" in conf
    assert "maxmemory 4gb" in conf
    assert "maxmemory-policy noeviction" in conf
    assert 'save ""' in conf
    assert "daemonize no" in conf
    assert f"dir {fake_repo / 'state' / 'services' / 'redis' / 'data'}" in conf
    assert f"pidfile {fake_repo / 'state' / 'services' / 'redis' / 'redis.pid'}" in conf

    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets["redis"]["password"] == pw


def test_native_redis_rotate_updates_config_and_files(fake_repo):
    _run(fake_repo, "redis-bootstrap.sh", "--native")
    conf1 = (fake_repo / "state" / "services" / "redis" / "redis.conf").read_text()
    pw1 = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]
    assert f"requirepass {pw1}" in conf1

    r = _run(fake_repo, "redis-bootstrap.sh", "--native", "--rotate")
    assert r.returncode == 0
    pw2 = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]
    assert pw2 != pw1
    conf2 = (fake_repo / "state" / "services" / "redis" / "redis.conf").read_text()
    assert f"requirepass {pw2}" in conf2
    assert f"requirepass {pw1}" not in conf2
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets["redis"]["password"] == pw2


def test_native_redis_pid_refuses_second_copy(fake_repo):
    r1 = _run(fake_repo, "redis-bootstrap.sh", "--native")
    assert r1.returncode == 0
    pid1 = int((fake_repo / "state" / "services" / "redis" / "redis.pid").read_text().strip())

    r2 = _run(fake_repo, "redis-bootstrap.sh", "--native")
    assert r2.returncode == 0
    pid2 = int((fake_repo / "state" / "services" / "redis" / "redis.pid").read_text().strip())
    assert pid1 == pid2
    assert "already running" in (r2.stdout + r2.stderr).lower()


def test_mode_choice_default_uses_container_when_docker_present(fake_repo):
    docker_stub = "#!/bin/sh\n[ \"$1\" = \"compose\" ] && exit 0\n[ \"$1\" = \"ps\" ] && exit 0\nexit 1\n"
    r = _run(
        fake_repo,
        "redis-bootstrap.sh",
        extra_stubs={"docker": docker_stub},
    )
    assert r.returncode == 0
    assert "docker compose -f compose/redis.yml up -d" in r.stdout


def test_mode_choice_native_flag_ignores_docker(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh", "--native")
    assert r.returncode == 0
    assert "docker compose" not in r.stdout
    assert (fake_repo / "state" / "services" / "redis" / "redis.conf").exists()


def test_mode_choice_default_falls_back_to_native_without_docker(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh", omit_stubs=["docker"])
    assert r.returncode == 0
    assert "docker compose" not in r.stdout
    assert (fake_repo / "state" / "services" / "redis" / "redis.conf").exists()


def test_mode_choice_container_without_docker_errors(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh", "--container", omit_stubs=["docker"])
    assert r.returncode != 0
    assert "docker" in (r.stdout + r.stderr).lower()


def test_qdrant_native_sha256_refusal(fake_repo):
    qdrant_script = b"#!/bin/sh\nwhile true; do sleep 1; done\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="qdrant")
        info.size = len(qdrant_script)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(qdrant_script))
    fixture = fake_repo / "fake-qdrant.tar.gz"
    fixture.write_bytes(buf.getvalue())

    _qdrant_curl_stub(fake_repo, fixture)

    # The pinned digest does not match the served archive: it must be refused.
    wrong = "0" * 64
    r = _run(
        fake_repo,
        "qdrant-bootstrap.sh",
        "--native",
        extra_env={"QDRANT_X86_64_SHA256": wrong, "QDRANT_AARCH64_SHA256": wrong},
    )
    assert r.returncode != 0
    assert "sha256 mismatch" in (r.stdout + r.stderr).lower()
    assert not (fake_repo / "state" / "services" / "qdrant" / "bin" / "qdrant").exists()


def test_qdrant_native_valid_download_and_readyz(fake_repo):
    qdrant_script = b"#!/bin/sh\nwhile true; do sleep 1; done\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="qdrant")
        info.size = len(qdrant_script)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(qdrant_script))
    fixture = fake_repo / "fake-qdrant.tar.gz"
    fixture.write_bytes(buf.getvalue())

    _qdrant_curl_stub(fake_repo, fixture)

    r = _run(
        fake_repo,
        "qdrant-bootstrap.sh",
        "--native",
        env=_qdrant_sha_env(fake_repo, fixture),
    )
    assert r.returncode == 0
    assert (fake_repo / "state" / "services" / "qdrant" / "bin" / "qdrant").exists()
    assert (fake_repo / "state" / "services" / "qdrant" / "qdrant.pid").exists()

    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    env_vals = _parse_env(fake_repo / "compose" / ".env")
    assert secrets["qdrant"]["api_key"] == env_vals["KAINE_QDRANT_API_KEY"]


def test_termux_qdrant_skips_with_sqlite_vec_guidance(fake_repo):
    r = _run(
        fake_repo,
        "qdrant-bootstrap.sh",
        env={"TERMUX_VERSION": "0.118"},
    )
    assert r.returncode == 0
    assert "sqlite_vec" in (r.stdout + r.stderr).lower()
    assert not (fake_repo / "state" / "services" / "qdrant").exists()


def test_termux_redis_hints_when_redis_server_missing(fake_repo):
    r = _run(
        fake_repo,
        "redis-bootstrap.sh",
        "--native",
        omit_stubs=["redis-server"],
        env={"TERMUX_VERSION": "0.118"},
    )
    assert r.returncode != 0
    assert "pkg install redis" in (r.stdout + r.stderr)


def test_services_sh_status_reports_container(fake_repo):
    docker_stub = (
        "#!/bin/sh\n"
        '[ "$1" = "ps" ] && { echo kaine-redis; echo kaine-qdrant; }\n'
        "exit 0\n"
    )
    r = _run(
        fake_repo,
        "services.sh",
        "status",
        "all",
        extra_stubs={"docker": docker_stub},
    )
    assert r.returncode == 0
    assert "container (running)" in r.stdout


def test_services_sh_native_pid_start_status_stop(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh", "--native")
    assert r.returncode == 0

    r = _run(fake_repo, "services.sh", "status", "redis")
    assert r.returncode == 0
    assert "native (running)" in r.stdout

    r = _run(fake_repo, "services.sh", "start", "redis")
    assert r.returncode != 0
    assert "already running" in (r.stdout + r.stderr).lower()

    r = _run(fake_repo, "services.sh", "stop", "redis")
    assert r.returncode == 0

    r = _run(fake_repo, "services.sh", "status", "redis")
    assert "not running" in r.stdout


def test_qdrant_compose_uses_pinned_version():
    text = (REPO / "compose" / "qdrant.yml").read_text()
    assert "qdrant/qdrant:v1.19.1" in text


def test_qdrant_local_archive_is_still_checked_against_the_pin(fake_repo):
    # An offline archive must pass the same sha256 check as a download.
    bad = fake_repo / "offline.tar.gz"
    bad.write_bytes(b"not the pinned release")
    wrong = "0" * 64
    r = _run(
        fake_repo,
        "qdrant-bootstrap.sh",
        "--native",
        extra_env={
            "KAINE_QDRANT_ARCHIVE": str(bad),
            "QDRANT_X86_64_SHA256": wrong,
            "QDRANT_AARCH64_SHA256": wrong,
        },
    )
    assert r.returncode != 0
    assert "sha256 mismatch" in (r.stdout + r.stderr).lower()
    assert not (fake_repo / "state" / "services" / "qdrant" / "bin" / "qdrant").exists()


def _logging_docker_stub(log_path):
    # Reports kaine-redis/kaine-qdrant as running containers and records argv.
    return (
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {str(log_path)!r}\n"
        "if [ \"$1\" = \"ps\" ]; then printf 'kaine-redis\\nkaine-qdrant\\n'; exit 0; fi\n"
        "[ \"$1\" = \"compose\" ] && exit 0\n"
        "exit 1\n"
    )


def test_services_stop_refuses_a_shared_container_without_the_flag(fake_repo):
    log = fake_repo / "docker-argv.log"
    r = _run(
        fake_repo,
        "services.sh",
        "stop",
        "redis",
        extra_stubs={"docker": _logging_docker_stub(log)},
    )
    assert r.returncode != 0
    assert "--container" in r.stderr
    calls = log.read_text() if log.exists() else ""
    assert " stop" not in calls and " down" not in calls


def test_services_stop_with_the_flag_stops_and_never_removes(fake_repo):
    log = fake_repo / "docker-argv.log"
    r = _run(
        fake_repo,
        "services.sh",
        "stop",
        "redis",
        "--container",
        extra_stubs={"docker": _logging_docker_stub(log)},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text()
    assert "compose -f compose/redis.yml stop" in calls
    assert " down" not in calls
