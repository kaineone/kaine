# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consented, hardware-aware download of the published KAINE language organ.

The language organ is published under the project's own account — Apache-2.0,
honest model card:

  - ``kaineone/Qwen3.5-4B-abliterated-GGUF``   (GGUF, served by the
    OpenAI-compatible llama-server — the always-needed artifact)
  - ``kaineone/Qwen3.5-4B-abliterated``        (safetensors base — only needed as
    the Stage-2 voice-alignment trainer's ``base_model_path``)

A fresh clone has NO weights. This module gives the first-run wizard a real,
consented, hardware-aware acquisition of the organ so "clone → install → run"
resolves identical weights for every researcher, instead of a manual scavenger
hunt against a wrong default. It mirrors the detect-and-guide pattern in
:mod:`kaine.setup.dependencies` / :mod:`kaine.setup.trainer_provisioning`:

  - ``detect_organ_backend()`` reuses the GPU-vendor detection (CUDA → the
    Unsloth Studio direction, ROCm → unsloth-core, anything else → guide-only).
  - ``plan_organ_download()`` decides which repo(s)+format(s) are needed for the
    host's role (GGUF always; +safetensors iff Stage-2 training is enabled) and
    returns the EXACT command(s) plus a size estimate — nothing for a non-lingua
    install.
  - ``run_organ_download()`` runs a **real** ``hf download`` (real subprocess,
    real success/failure; never a faked/no-op "installed" result) and captures the
    resolved repo revision (commit sha) when the tool reports it.
  - ``verify_served_alias()`` probes ``{chat_url}/models`` for the exact configured
    alias, converting a boot-time 404 into a pre-boot, operator-facing message.

No pretend processes: a download is a real ``hf download`` or it fails honestly;
a probe that cannot run reports the gap rather than guessing.
"""
from __future__ import annotations

import codecs
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.organ_probe import ORGAN_REVISION_STATE_PATH
from kaine.organ_server.served import (
    ORGAN_GGUF_FILE,
    ORGAN_GGUF_REPO,
    ORGAN_SAFETENSORS_REPO,
    OrganBackend,
    organ_gguf_dir,
)
from kaine.storage import resolve

# Rough download sizes (GiB) for the operator-facing "bytes up front" message.
# The 4B GGUF (q4-ish) is a few GiB; the safetensors base is the full-precision
# checkpoint. Honest estimates, not promises — ``hf download`` reports the real
# bytes as it runs.
_GGUF_SIZE_GB = 3.0
_SAFETENSORS_SIZE_GB = 8.0


@dataclass(frozen=True)
class OrganArtifact:
    """One repo+format the host needs, with its exact download command."""

    repo: str
    fmt: str               # "gguf" | "safetensors"
    reason: str
    size_gb: float
    command: list[str]     # exact argv (hf download ...)


@dataclass(frozen=True)
class OrganDownloadPlan:
    """The organ-acquisition plan for a host's chosen modules + backend.

    ``artifacts`` is empty when the organ is not needed (lingua disabled): the
    wizard then offers no download step at all.
    """

    needed: bool
    backend: OrganBackend
    artifacts: tuple[OrganArtifact, ...] = ()

    @property
    def total_size_gb(self) -> float:
        return round(sum(a.size_gb for a in self.artifacts), 1)


def _lingua_enabled(modules: dict[str, Any]) -> bool:
    return bool((modules or {}).get("lingua"))


def _stage2_enabled(config: dict[str, Any]) -> bool:
    """True iff on-device voice-alignment (Stage-2) training is enabled.

    Stage-2 needs the safetensors base as the trainer's ``base_model_path``; a
    serve-only host skips it. Gated on BOTH the hypnos module toggle and
    ``[hypnos.voice_alignment].enabled`` (the master gate)."""
    modules = config.get("modules") or {}
    if not modules.get("hypnos"):
        return False
    va = (config.get("hypnos") or {}).get("voice_alignment") or {}
    return bool(va.get("enabled"))


def _hf_download_cmd(repo: str) -> list[str]:
    """The real ``hf download <repo>`` argv (HF Hub CLI; resumes + verifies)."""
    return ["hf", "download", repo]


def _gguf_download_cmd() -> list[str]:
    """Real ``hf download`` of the single GGUF file into the deterministic local
    dir, so the server can be launched with ``-m <served_gguf_path()>`` (a real file
    path). ``--local-dir`` makes the landing path known and stable, independent of
    the hub-cache snapshot layout."""
    local_dir = organ_gguf_dir()
    return [
        "hf", "download", ORGAN_GGUF_REPO, ORGAN_GGUF_FILE,
        "--local-dir", str(local_dir),
    ]


def plan_organ_download(
    modules: dict[str, Any],
    backend: OrganBackend,
    *,
    config: Optional[dict[str, Any]] = None,
) -> OrganDownloadPlan:
    """Decide which repo(s)+format(s) the host needs and the exact command(s).

    GGUF is always required (what the OpenAI-compatible server serves);
    safetensors is added ONLY when Stage-2 voice-alignment training is enabled
    (the trainer's base model). Returns an empty plan (``needed=False``) when
    lingua is not enabled — the wizard then offers no organ step.

    ``config`` is the resolved config used to read the Stage-2 toggle; when None it
    is derived from ``modules`` alone (Stage-2 treated as off). Pure: builds the
    plan, runs nothing.
    """
    if not _lingua_enabled(modules):
        return OrganDownloadPlan(needed=False, backend=backend, artifacts=())

    cfg = config if config is not None else {"modules": modules}
    artifacts: list[OrganArtifact] = [
        OrganArtifact(
            repo=ORGAN_GGUF_REPO,
            fmt="gguf",
            reason="served by the OpenAI-compatible model server (always needed)",
            size_gb=_GGUF_SIZE_GB,
            command=_gguf_download_cmd(),
        )
    ]
    if _stage2_enabled(cfg):
        artifacts.append(
            OrganArtifact(
                repo=ORGAN_SAFETENSORS_REPO,
                fmt="safetensors",
                reason="Stage-2 voice-alignment trainer base_model_path",
                size_gb=_SAFETENSORS_SIZE_GB,
                command=_hf_download_cmd(ORGAN_SAFETENSORS_REPO),
            )
        )
    return OrganDownloadPlan(
        needed=True, backend=backend, artifacts=tuple(artifacts)
    )


@dataclass
class OrganDownloadResult:
    """Outcome of one artifact download. ``revision`` is the resolved commit sha
    when ``hf`` reported it (for the run-manifest covariate), else None."""

    repo: str
    fmt: str
    ok: bool
    revision: Optional[str] = None
    detail: str = ""


# `hf download` prints the local snapshot path, which embeds the resolved commit
# sha: .../snapshots/<40-hex-sha>/...  We capture that sha as the pinned revision.
_SNAPSHOT_SHA_RE = re.compile(r"/snapshots/([0-9a-f]{40})\b")


def _extract_revision(output: str) -> Optional[str]:
    m = _SNAPSHOT_SHA_RE.search(output or "")
    return m.group(1) if m else None


def _revision_from_local_dir_metadata(command: tuple[str, ...]) -> Optional[str]:
    """Read a Hugging Face download commit hash from local-dir metadata.

    The metadata file lives at ``<dir>/.cache/huggingface/download/<file>.metadata``
    where ``<dir>`` is the ``--local-dir`` value and ``<file>`` is the positional
    file argument after the repo in the command.  Only a 40-character lowercase
    hex first line is accepted.  Never raises.
    """
    try:
        idx = command.index("--local-dir")
        local_dir = command[idx + 1]
    except (ValueError, IndexError):
        return None
    positional = [arg for arg in command if not arg.startswith("-")]
    if len(positional) < 4:
        return None
    filename = positional[3]
    metadata_path = (
        Path(local_dir) / ".cache" / "huggingface" / "download" / f"{filename}.metadata"
    )
    try:
        first_line = metadata_path.read_text().splitlines()[0].strip()
    except Exception:
        return None
    if re.fullmatch(r"[0-9a-f]{40}", first_line):
        return first_line
    return None


def run_organ_download(
    plan: OrganDownloadPlan,
    *,
    consent: bool,
    runner: Any = None,
    stream: Callable[[str], None] | None = None,
) -> list[OrganDownloadResult]:
    """Run the planned organ download(s) — a REAL ``hf download`` per artifact.

    Runs ONLY on explicit ``consent``; with ``consent=False`` it runs nothing and
    returns ``[]`` (the wizard prints the guide instead). The ``hf`` CLI must be
    on PATH; if it is absent each artifact reports an honest failure (no faked
    success). Each ``hf download`` is a real subprocess (``check=True`` caught) and
    its output is scanned for the resolved snapshot sha, recorded as the pinned
    revision. Never raises — a failed download is reported as ``ok=False``.

    ``runner`` defaults to ``subprocess.run`` (overridable in tests with a mocked
    subprocess; the production path always invokes the real CLI).

    When ``stream`` is provided and ``runner`` is ``None``, output is streamed
    to ``stream`` incrementally (used by the setup web UI for live progress) while
    the last 64 KiB is retained for revision extraction.
    """
    if not consent or not plan.needed or not plan.artifacts:
        return []

    run = runner if runner is not None else subprocess.run
    have_hf = shutil.which("hf") is not None

    results: list[OrganDownloadResult] = []
    for art in plan.artifacts:
        if not have_hf:
            results.append(
                OrganDownloadResult(
                    repo=art.repo,
                    fmt=art.fmt,
                    ok=False,
                    detail=(
                        "the Hugging Face CLI (`hf`) is not on PATH — install it "
                        "(`pip install -U huggingface_hub`) then re-run: "
                        + " ".join(art.command)
                    ),
                )
            )
            continue

        if stream is not None and runner is None:
            tail = ""
            returncode = 0
            try:
                proc = subprocess.Popen(
                    art.command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while True:
                    chunk = proc.stdout.read1(65536)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    stream(text)
                    tail += text
                    if len(tail) > 65536:
                        tail = tail[-65536:]
                returncode = proc.wait()
            except Exception as exc:
                results.append(
                    OrganDownloadResult(
                        repo=art.repo,
                        fmt=art.fmt,
                        ok=False,
                        detail=f"could not run hf download ({type(exc).__name__}: {exc})",
                    )
                )
                continue
            if returncode != 0:
                lines = [ln for ln in tail.splitlines() if ln.strip()]
                reason = lines[-1] if lines else f"exit {returncode}"
                results.append(
                    OrganDownloadResult(
                        repo=art.repo,
                        fmt=art.fmt,
                        ok=False,
                        detail=f"download failed ({reason})",
                    )
                )
                continue
            revision = _extract_revision(tail)
            if revision is None:
                revision = _revision_from_local_dir_metadata(art.command)
            results.append(
                OrganDownloadResult(
                    repo=art.repo,
                    fmt=art.fmt,
                    ok=True,
                    revision=revision,
                    detail=(
                        f"downloaded (revision {revision})"
                        if revision
                        else "downloaded"
                    ),
                )
            )
            continue

        try:
            proc = run(
                art.command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            tail = (exc.stderr or exc.stdout or "").strip().splitlines()
            reason = tail[-1] if tail else f"exit {exc.returncode}"
            results.append(
                OrganDownloadResult(
                    repo=art.repo, fmt=art.fmt, ok=False,
                    detail=f"download failed ({reason})",
                )
            )
            continue
        except Exception as exc:  # OSError launching, etc.
            results.append(
                OrganDownloadResult(
                    repo=art.repo, fmt=art.fmt, ok=False,
                    detail=f"could not run hf download ({type(exc).__name__}: {exc})",
                )
            )
            continue
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        revision = _extract_revision(out)
        if revision is None:
            revision = _revision_from_local_dir_metadata(art.command)
        results.append(
            OrganDownloadResult(
                repo=art.repo,
                fmt=art.fmt,
                ok=True,
                revision=revision,
                detail=(
                    f"downloaded (revision {revision})"
                    if revision
                    else "downloaded"
                ),
            )
        )
    return results


def acquisition_guide(backend: OrganBackend, plan: OrganDownloadPlan) -> list[str]:
    """Operator-facing acquisition guidance lines (printed on decline / no GPU).

    Shows the published repos, the exact ``hf download`` command(s), and the
    hardware-appropriate serve direction — never an auto-install."""
    lines = [f"  {backend.summary}"]
    if plan.needed:
        for art in plan.artifacts:
            lines.append(
                f"    - {art.fmt}: huggingface.co/{art.repo} "
                f"(~{art.size_gb:.0f} GB; {art.reason})"
            )
            lines.append(f"        download: {' '.join(art.command)}")
        lines.append(
            "    Then serve the GGUF with the model server bootstrap: "
            "bash scripts/model-server-bootstrap.sh start"
        )
    return lines


def revisions_from_results(
    results: list[OrganDownloadResult],
) -> dict[str, str]:
    """Map ``<repo> -> <revision sha>`` for the resolved downloads.

    Used to persist provenance (the pinned published snapshot) for the run
    manifest. Only artifacts whose revision was resolved are included."""
    return {r.repo: r.revision for r in results if r.ok and r.revision}


def write_revision_state(
    results: list[OrganDownloadResult],
    *,
    path: Optional[str] = None,
) -> Optional[str]:
    """Persist resolved organ revision(s) to a small state file (best-effort).

    Returns the path written, or None if there was nothing to record / the write
    failed. Never raises."""
    revisions = revisions_from_results(results)
    if not revisions:
        return None
    target = resolve(path or ORGAN_REVISION_STATE_PATH)
    try:
        from kaine.state_io import write_json_atomic

        write_json_atomic(target, revisions)
        return str(target)
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the consented organ download step.

    Loads the merged operator configuration, plans the download, runs it with
    explicit consent, prints one line per artifact, records revisions for
    provenance exactly as the terminal path does, and exits non-zero if any
    artifact failed.  Never prints a token.
    """
    import argparse
    from pathlib import Path

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="python -m kaine.setup.organ")
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_p = subparsers.add_parser("download")
    download_p.add_argument("--yes", action="store_true")
    download_p.add_argument("--config", type=Path, default=None)
    download_p.add_argument("--operator-config", type=Path, default=None)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.command != "download":
        return 2

    if not args.yes:
        print("download requires --yes to confirm", file=sys.stderr)
        return 2

    # Lazy imports to keep ``kaine.setup.organ``'s import graph unchanged.
    from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, load_kaine_config
    from kaine.hardware import describe_host
    from kaine.organ_server.served import detect_organ_backend

    shipped_config_path = args.config if args.config is not None else SHIPPED_CONFIG_PATH
    operator_config_path = (
        args.operator_config if args.operator_config is not None else OPERATOR_CONFIG_PATH
    )

    config = load_kaine_config(shipped_config_path, operator_path=operator_config_path)
    host = describe_host()
    modules = config.get("modules") or {}

    try:
        backend = detect_organ_backend(str(host.get("backend") or "cpu"))
        plan = plan_organ_download(modules, backend, config=config)
    except Exception as exc:
        print(f"organ planning error: {exc}", file=sys.stderr)
        return 1

    print(backend.summary)

    if not plan.needed or not plan.artifacts:
        print("No organ download needed for this configuration.")
        return 0

    if not backend.available:
        for ln in acquisition_guide(backend, plan):
            print(ln)
        return 1

    results = run_organ_download(
        plan,
        consent=True,
        stream=lambda s: (sys.stdout.write(s), sys.stdout.flush()),
    )
    all_ok = bool(results) and all(r.ok for r in results)

    for r in results:
        tag = "ok" if r.ok else "FAILED"
        print(f"[{tag}] {r.repo} — {r.detail}")

    if all_ok:
        revisions = revisions_from_results(results)
        if not revisions:
            print(
                "The download did not report a revision; "
                "nothing was recorded for provenance."
            )
        else:
            state_written = write_revision_state(results)
            if state_written:
                print(f"Recorded organ revision(s) for provenance: {state_written}")
            else:
                target = resolve(ORGAN_REVISION_STATE_PATH)
                print(
                    f"Warning: the organ revision(s) could not be written to {target}; "
                    "check that the state directory is writable.",
                    file=sys.stderr,
                )

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
