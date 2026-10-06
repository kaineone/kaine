# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""FastAPI loopback setup server (KAINE)."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import socket
import time
import tomllib
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from kaine.config import load_kaine_config
from kaine.hardware import describe_host
from kaine.setup import tomlwriter
from kaine.setup.steps import (
    OWNED_KEYS,
    Field,
    Step,
    StepContext,
    owned_changes,
)
from kaine.setup.web import guard, job_specs, session
from kaine.setup.web.driver import validate_fields
from kaine.setup.web.jobs import JobRunner
from kaine.setup.wizard import ACK_PHRASE
from kaine.setup.wizard_steps import ack_step, orientation_step, setup_steps

# Steps whose ``apply`` calls ``ctx.extra["input_fn"]`` because they need
# interactive yes/no decisions that cannot be expressed as declarative fields.
# The web renders the questions below as form fields and replays the answers
# through the same input function the terminal wizard uses.
#
#   accelerator-mismatch: prompts depend on runtime probe results; the web
#       page shows the step and uses safe defaults for any unanswered prompt.
#   trainer-provisioning:
#       1. "Set up the sleep-cycle voice-alignment trainer now?" (default no)
#       2. If setup is wanted and a probe finds an interpreter:
#          "Record <interpreter> as the voice-alignment trainer?" (default yes)
#   cl1-substrate:
#       1. "Set up the CL1 substrate plugin?" (default no)
_HELPER_STEP_IDS = frozenset(
    {"accelerator-mismatch", "trainer-provisioning", "cl1-substrate"}
)

_MAX_FORM_BYTES = 64 * 1024


async def _read_form(request: Request) -> dict[str, str | list[str]]:
    """Parse an ``application/x-www-form-urlencoded`` body without python-multipart.

    Single-key values are returned as strings; repeated keys are returned as
    lists so multichoice checkboxes work.
    """
    body = await request.body()
    if len(body) > _MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="form too large")
    if not body:
        # A form with no successful controls (a step with no fields, or every
        # checkbox unticked) may arrive with no body and no content type.
        return {}
    ct = request.headers.get("content-type", "")
    if not ct.startswith("application/x-www-form-urlencoded"):
        raise HTTPException(status_code=415, detail="unsupported media type")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="form is not valid UTF-8")
    parsed = parse_qs(text, keep_blank_values=True)
    result: dict[str, str | list[str]] = {}
    for key, values in parsed.items():
        if len(values) == 1:
            result[key] = values[0]
        else:
            result[key] = values
    return result


@dataclass
class SetupState:
    """Per-app setup driver state."""

    steps: list[Step]
    store: session.LaunchSessionStore
    host: dict[str, Any]
    shipped: dict[str, Any]
    existing: dict[str, Any]
    operator_path: Path
    state_root: Path
    idle_seconds: float
    storage_old_root: Path
    templates: Jinja2Templates = field(repr=False)
    static_dir: Path = field(default=Path("."), repr=False)
    probe_services: Callable[[], dict[str, Any]] | None = None
    probe_trainer: Callable[..., tuple[bool, str]] | None = None
    torch_cuda_probes: dict[str, Any] | None = None
    corrective_install_fn: Callable[[str], bool] | None = None
    wheel_index_url: str | None = None
    recommend_tier_fn: Callable[[], Any] | None = None
    device_consumers_fn: Callable[[], list[dict]] | None = None
    services_up_fn: Callable[[], dict[str, bool]] | None = None
    shipped_config_path: Path | None = None


class _NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response


class _SessionMiddleware(BaseHTTPMiddleware):
    """Require a valid session cookie except for the launch-token exchange."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        store = request.app.state.setup.store
        path = request.url.path

        # The token exchange endpoint is allowed through without a session,
        # but it is responsible for its own last-activity update.
        if path == "/" and "token" in request.query_params:
            return await call_next(request)

        sid = request.cookies.get("setup_session")
        if not sid or sid not in store.sessions:
            return PlainTextResponse(
                "session required",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        request.state.session = store.sessions[sid]
        request.app.state.last_activity = store.now()
        return await call_next(request)


def _noop_line(_text: str = "") -> None:
    pass


def _noop_input(_prompt: str) -> str:
    """Safe fallback for steps that should not prompt in the browser."""
    return ""


def _load_shipped(path: Path) -> dict[str, Any]:
    try:
        return load_kaine_config(path, operator_path=Path("/nonexistent"))
    except FileNotFoundError:
        return {}


def _load_existing(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise ValueError(
            f"could not read existing operator file at {path}: {exc}"
        ) from exc


def _run_probes(state: SetupState, sess: dict[str, Any]) -> None:
    """Populate session extras with post-acknowledgement probe results."""
    from kaine.setup.hardware_steps import load_footprint_catalogue

    discovered: dict[str, Any] = {}
    if state.probe_services is not None:
        try:
            discovered = state.probe_services() or {}
        except Exception:
            discovered = {}

    tier_rec = None
    if state.recommend_tier_fn is not None:
        try:
            tier_rec = state.recommend_tier_fn()
        except Exception:
            tier_rec = None

    catalogue: dict[str, Any] = {}
    try:
        catalogue = load_footprint_catalogue()
    except Exception:
        catalogue = {}

    consumers = state.device_consumers_fn() if state.device_consumers_fn else None
    services_up = state.services_up_fn() if state.services_up_fn else {}

    floor_gb = float(
        ((state.shipped.get("gpu_preflight") or {}).get("min_free_vram_gb", 2.0))
    )
    min_free_gb = float(
        ((state.shipped.get("storage") or {}).get("min_free_gb", 20.0))
    )

    sess["extra"].update(
        {
            "discovered": discovered,
            "consumers": consumers,
            "catalogue": catalogue,
            "floor_gb": floor_gb,
            "services_up": services_up,
            "tier_rec": tier_rec,
            "old_root": state.storage_old_root,
            "min_free_gb": min_free_gb,
            "probe_trainer": state.probe_trainer,
            "torch_cuda_probes": state.torch_cuda_probes,
            "corrective_install_fn": state.corrective_install_fn,
            "wheel_index_url": state.wheel_index_url,
        }
    )


def _make_ctx(
    state: SetupState,
    sess: dict[str, Any],
    input_fn: Callable[[str], str] = _noop_input,
) -> StepContext:
    extra = copy.deepcopy(sess["extra"])
    extra["input_fn"] = input_fn
    extra["out"] = _noop_line
    extra.setdefault("defaults", False)
    extra.setdefault("shipped_config", state.shipped)
    extra.setdefault("existing_config", state.existing)
    return StepContext(config=sess["config"], host=state.host, extra=extra)


def _current_step(state: SetupState, sess: dict[str, Any]) -> tuple[Step | None, int]:
    idx = sess["step_index"]
    if idx >= len(state.steps):
        return None, idx
    return state.steps[idx], idx


def _advance_to_applicable(
    state: SetupState, sess: dict[str, Any], ctx: StepContext
) -> Step | None:
    """Move the session past steps that do not apply (as ``run_step`` skips
    them in the terminal) and return the current applicable step, or None
    when every step is done."""
    step, _idx = _current_step(state, sess)
    while step is not None and not step.applies(ctx):
        sess["step_index"] += 1
        step, _idx = _current_step(state, sess)
    return step


def _require_done(state: SetupState, sess: dict[str, Any]) -> PlainTextResponse | None:
    if not sess.get("acknowledged") or sess["step_index"] < len(state.steps):
        return PlainTextResponse(
            "forbidden",
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    return None


async def _idle_watcher(app: FastAPI) -> None:
    """Stop the server after idle timeout or an explicit finish signal."""
    setup = app.state.setup
    while True:
        await asyncio.sleep(1)
        if getattr(app.state, "finish_shutdown", False):
            server = getattr(app.state, "server", None)
            if server is not None:
                server.should_exit = True
            return
        if getattr(app.state, "activity_hold", 0) > 0:
            continue
        last = getattr(app.state, "last_activity", setup.store.now())
        if (setup.store.now() - last) > setup.idle_seconds:
            server = getattr(app.state, "server", None)
            if server is not None:
                server.should_exit = True
            return


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.shutting_down = False
    app.state.last_activity = app.state.setup.store.now()
    watcher = asyncio.create_task(_idle_watcher(app))
    yield
    app.state.shutting_down = True
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass
    try:
        await app.state.runner.shutdown()
    except Exception:
        logging.exception("error during runner shutdown")


def _helper_questions(step_id: str) -> tuple[dict[str, Any], ...]:
    """Return the yes/no questions a helper step asks, in prompt order."""
    if step_id == "trainer-provisioning":
        return (
            {
                "name": "set_up_trainer",
                "label": "Set up the sleep-cycle voice-alignment trainer now?",
                "match": "set up the sleep-cycle voice-alignment trainer now?",
                "default": "no",
                "choices": ("yes", "no"),
            },
            {
                "name": "record_trainer",
                "label": "Record the detected interpreter as the voice-alignment trainer?",
                "match": "as the voice-alignment trainer?",
                "default": "yes",
                "choices": ("yes", "no"),
            },
        )
    if step_id == "cl1-substrate":
        return (
            {
                "name": "set_up_cl1",
                "label": "Set up the CL1 substrate plugin?",
                "match": "set up the cl1 substrate plugin?",
                "default": "no",
                "choices": ("yes", "no"),
            },
        )
    return ()


def _helper_fields(step_id: str) -> tuple[Field, ...]:
    """Return declarative fields for the yes/no helper questions."""
    return tuple(
        Field(
            name=q["name"],
            prompt=q["label"],
            kind="choice",
            default=q["default"],
            choices=q["choices"],
        )
        for q in _helper_questions(step_id)
    )


def _web_input(form: dict[str, Any], questions: tuple[dict[str, Any], ...]) -> Callable[[str], str]:
    """Build an input function that answers helper prompts from the POST form.

    Missing answers fall back to the empty string, which lets the helper use
    the safe default of its terminal prompt.
    """

    def _values(name: str) -> list[str]:
        value = form.get(name)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]

    def input_fn(prompt: str) -> str:
        p = prompt.lower()
        for q in questions:
            match = q["match"].lower()
            if match and match in p:
                values = _values(q["name"])
                if not values:
                    return ""
                last = values[-1].strip().lower()
                # The helpers read answers through _ask_yes_no, which accepts
                # only "y"/"yes"; anything else is "no".
                if last in {"yes", "y", "true", "on", "1"}:
                    return "yes"
                if last in {"no", "n", "false", "off", "0"}:
                    return "no"
                return values[-1]
        return ""

    return input_fn


def create_setup_app(
    state_root: Path,
    operator_path: Path,
    shipped_config_path: Path,
    idle_seconds: float = 1800.0,
    *,
    host: dict[str, Any] | None = None,
    probe_services: Callable[[], dict[str, Any]] | None = None,
    probe_trainer: Callable[..., tuple[bool, str]] | None = None,
    torch_cuda_probes: dict[str, Any] | None = None,
    corrective_install_fn: Callable[[str], bool] | None = None,
    wheel_index_url: str | None = None,
    recommend_tier_fn: Callable[[], Any] | None = None,
    device_consumers_fn: Callable[[], list[dict]] | None = None,
    services_up_fn: Callable[[], dict[str, bool]] | None = None,
    storage_old_root: Path | None = None,
    now: Callable[[], float] | None = None,
) -> FastAPI:
    """Build the loopback setup server application.

    All filesystem paths are explicit so tests can use temporary directories.
    The server never starts subprocesses in this slice.
    """
    if host is None:
        host = describe_host()
        host["cpu_count"] = os.cpu_count()

    shipped = _load_shipped(shipped_config_path)
    existing = _load_existing(operator_path)

    if storage_old_root is None:
        data_root = (existing.get("storage") or {}).get("data_root")
        storage_old_root = Path(data_root) if data_root else Path.cwd()

    static_dir = Path(__file__).resolve().parents[2] / "nexus" / "static"
    if not static_dir.exists() or not static_dir.is_dir():
        raise ValueError(f"Nexus static directory not found at {static_dir}")

    store = session.LaunchSessionStore(ttl_seconds=120.0, now=now or time.time)

    templates_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    steps = [orientation_step(), ack_step()] + setup_steps(storage_old_root is not None)

    app = FastAPI(lifespan=_lifespan)
    app.state.setup = SetupState(
        steps=steps,
        store=store,
        host=host,
        shipped=shipped,
        existing=existing,
        operator_path=operator_path,
        state_root=state_root,
        idle_seconds=idle_seconds,
        storage_old_root=storage_old_root,
        templates=templates,
        static_dir=static_dir,
        probe_services=probe_services,
        probe_trainer=probe_trainer,
        torch_cuda_probes=torch_cuda_probes,
        corrective_install_fn=corrective_install_fn,
        wheel_index_url=wheel_index_url,
        recommend_tier_fn=recommend_tier_fn,
        device_consumers_fn=device_consumers_fn,
        services_up_fn=services_up_fn,
        shipped_config_path=shipped_config_path,
    )
    repo_root = Path(__file__).resolve().parents[3]
    app.state.repo_root = repo_root
    app.state.shipped_config_path = shipped_config_path
    app.state.last_activity = store.now()
    app.state.finish_shutdown = False
    app.state.activity_hold = 0

    app.state.runner = JobRunner(repo_root=repo_root, hold=app.state)

    # Middleware order (innermost first): session, no-cache, host/origin.
    app.add_middleware(_SessionMiddleware)
    app.add_middleware(_NoCacheMiddleware)
    app.add_middleware(guard.HostOriginMiddleware)

    @app.get("/", name="root")
    async def root(request: Request, token: str | None = None):
        state = request.app.state.setup
        if token is None:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "status": 403,
                    "message": "A launch token is required.",
                },
                status_code=403,
            )

        sid = state.store.exchange(token)
        if sid is None:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "status": 403,
                    "message": (
                        "This launch link has expired, already been used, "
                        "or is invalid."
                    ),
                },
                status_code=403,
            )

        response = RedirectResponse(
            request.url_for("step_get"), status_code=303
        )
        response.headers["set-cookie"] = (
            f"setup_session={sid}; HttpOnly; SameSite=Strict; Path=/"
        )
        request.app.state.last_activity = state.store.now()
        return response

    @app.get("/step", response_class=HTMLResponse, name="step_get")
    async def step_get(request: Request):
        state = request.app.state.setup
        sess = request.state.session
        step, _idx = _current_step(state, sess)
        if step is None:
            return RedirectResponse(request.url_for("review"), status_code=303)

        ctx = _make_ctx(state, sess)
        step = _advance_to_applicable(state, sess, ctx)
        if step is None:
            return RedirectResponse(request.url_for("review"), status_code=303)

        is_helper = step.id in _HELPER_STEP_IDS
        if is_helper:
            fields = _helper_fields(step.id)
        else:
            fields = tuple(step.fields(ctx))

        field_dicts = [
            {
                "name": field.name,
                "prompt": field.prompt,
                "kind": field.kind,
                "default": field.default,
                "choices": field.choices,
            }
            for field in fields
        ]

        return templates.TemplateResponse(
            request,
            "step.html",
            {
                "step": step,
                "explanation": step.explanation(ctx),
                "fields": field_dicts,
                "is_helper": is_helper,
                "errors": {},
                "values": {},
            },
        )

    @app.post("/step", name="step_post")
    async def step_post(request: Request):
        state = request.app.state.setup
        sess = request.state.session
        step, _idx = _current_step(state, sess)
        if step is None:
            return RedirectResponse(request.url_for("review"), status_code=303)

        # POST acts on the current applicable step, exactly the one GET shows;
        # a step that does not apply is passed over, never answered.
        ctx = _make_ctx(state, sess)
        step = _advance_to_applicable(state, sess, ctx)
        if step is None:
            return RedirectResponse(request.url_for("review"), status_code=303)
        form = await _read_form(request)
        posted_step_id = form.get("_step_id")
        if isinstance(posted_step_id, list):
            posted_step_id = posted_step_id[-1] if posted_step_id else None
        if posted_step_id != step.id:
            return PlainTextResponse(
                "this form is for a different step; reload the page",
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )
        is_helper = step.id in _HELPER_STEP_IDS
        if is_helper:
            fields = _helper_fields(step.id)
            questions = _helper_questions(step.id)
        else:
            fields = tuple(step.fields(ctx))
            questions = ()

        answers, errors = validate_fields(fields, form)

        if step.id == "welfare-acknowledgement":
            if answers.get("ack") != ACK_PHRASE:
                request.app.state.finish_shutdown = True
                return templates.TemplateResponse(
                    request,
                    "done.html",
                    {
                        "abort": True,
                        "message": (
                            "Acknowledgement not given; aborting. No configuration was written."
                        ),
                    },
                )
            sess["acknowledged"] = True
            _run_probes(state, sess)

        if errors:
            field_dicts = [
                {
                    "name": field.name,
                    "prompt": field.prompt,
                    "kind": field.kind,
                    "default": field.default,
                    "choices": field.choices,
                }
                for field in fields
            ]
            return templates.TemplateResponse(
                request,
                "step.html",
                {
                    "step": step,
                    "explanation": step.explanation(ctx),
                    "fields": field_dicts,
                    "is_helper": is_helper,
                    "errors": errors,
                    "values": answers,
                },
                status_code=400,
            )

        if is_helper:
            ctx.extra["input_fn"] = _web_input(form, questions)
        else:
            ctx.extra["input_fn"] = _noop_input

        step.apply(ctx, answers)

        sess["config"] = ctx.config
        # Per-request callables never enter the stored session.
        sess["extra"].update(
            {k: v for k, v in ctx.extra.items() if k not in ("input_fn", "out")}
        )
        sess["step_index"] += 1
        return RedirectResponse(request.url_for("step_get"), status_code=303)

    @app.get("/review", response_class=HTMLResponse, name="review")
    async def review(request: Request):
        state = request.app.state.setup
        sess = request.state.session
        forbidden = _require_done(state, sess)
        if forbidden is not None:
            return forbidden

        # Compare against the merged result, as the terminal does, so a
        # removal shows as the owned keys it deletes.
        try:
            preview = tomlwriter.merge_owned(
                state.existing, sess["config"], OWNED_KEYS
            )
        except ValueError:
            preview = sess["config"]
        changes = owned_changes(state.existing, preview)
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "changes": changes,
                "operator_path": state.operator_path,
            },
        )

    @app.post("/save", name="save")
    async def save(request: Request):
        state = request.app.state.setup
        sess = request.state.session

        forbidden = _require_done(state, sess)
        if forbidden is not None:
            return forbidden

        running, reason = guard.cycle_running_with_reason(state.state_root)
        if running:
            message = (
                "A KAINE cycle is currently running; configuration cannot be "
                "changed while it is active."
            )
            if reason:
                message += f" ({reason})"
            return PlainTextResponse(message, status_code=409)

        try:
            merged = tomlwriter.merge_owned(
                state.existing, sess["config"], OWNED_KEYS
            )
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "status": 400,
                    "message": f"Configuration cannot be saved: {exc}",
                },
                status_code=400,
            )

        tmp_path = state.operator_path.with_suffix(
            state.operator_path.suffix + ".tmp"
        )
        state.operator_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(tomlwriter.dumps(merged))
        os.replace(tmp_path, state.operator_path)

        sess["saved"] = True
        return RedirectResponse(request.url_for("jobs"), status_code=303)

    @app.get("/jobs", response_class=HTMLResponse, name="jobs")
    async def jobs(request: Request):
        state = request.app.state.setup
        sess = request.state.session
        if not sess.get("saved"):
            return PlainTextResponse(
                "configuration has not been saved",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        specs = job_specs.build_job_specs(
            sess["config"],
            state.shipped,
            repo_root=request.app.state.repo_root,
            shipped_config_path=state.shipped_config_path,
            operator_path=state.operator_path,
        )
        runner = request.app.state.runner
        jobs_info = []
        for spec in specs:
            job_id = runner.job_id_for_name(spec.name)
            st = runner.status(job_id) if job_id is not None else None
            jobs_info.append({"spec": spec, "job_id": job_id, "status": st})

        return templates.TemplateResponse(
            request,
            "jobs.html",
            {"jobs": jobs_info},
        )

    @app.post("/jobs/{name}/start", name="job_start")
    async def job_start(request: Request, name: str):
        state = request.app.state.setup
        sess = request.state.session
        if not sess.get("saved"):
            return PlainTextResponse(
                "configuration has not been saved",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        running, reason = await asyncio.to_thread(
            guard.cycle_running_with_reason, state.state_root
        )
        if running:
            return PlainTextResponse(
                f"an entity is running; jobs are refused ({reason})",
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )

        specs = {
            s.name: s
            for s in job_specs.build_job_specs(
                sess["config"],
                state.shipped,
                repo_root=request.app.state.repo_root,
                shipped_config_path=state.shipped_config_path,
                operator_path=state.operator_path,
            )
        }
        if name not in specs:
            raise HTTPException(status_code=404, detail="unknown job")

        try:
            job_id = await request.app.state.runner.start(name, specs[name])
        except RuntimeError as exc:
            return PlainTextResponse(
                str(exc),
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )

        sess.setdefault("job_ids", []).append(job_id)
        return RedirectResponse(request.url_for("jobs"), status_code=303)

    @app.get("/jobs/{job_id}/events")
    async def job_events(request: Request, job_id: str):
        runner = request.app.state.runner
        if job_id not in runner:
            raise HTTPException(status_code=404)

        sess = request.state.session
        if job_id not in sess.setdefault("job_ids", []):
            raise HTTPException(status_code=404)

        async def stream():
            async for item in runner.events(
                job_id,
                shutting_down=lambda: bool(
                    getattr(getattr(request.app.state, "server", None), "should_exit", False)
                )
                or request.app.state.shutting_down,
            ):
                if isinstance(item, str):
                    yield f"data: {item}\n\n"
                else:
                    payload = json.dumps(item, separators=(",", ":"))
                    yield f"event: done\ndata: {payload}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/jobs/{job_id}/cancel", name="job_cancel")
    async def job_cancel(request: Request, job_id: str):
        runner = request.app.state.runner
        if job_id not in runner:
            raise HTTPException(status_code=404)

        sess = request.state.session
        if job_id not in sess.setdefault("job_ids", []):
            raise HTTPException(status_code=404)

        if not runner.cancel(job_id):
            return PlainTextResponse(
                "job is not running",
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )

        if "application/json" in request.headers.get("accept", ""):
            return {"status": "cancelled"}
        return RedirectResponse(request.url_for("jobs"), status_code=303)

    @app.post("/finish", response_class=HTMLResponse, name="finish")
    async def finish(request: Request):
        runner = request.app.state.runner
        sess = request.state.session
        if not sess.get("saved"):
            # Ending setup without a saved configuration is Abort, not Finish.
            return PlainTextResponse(
                "configuration has not been saved",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        for job_id in sess.setdefault("job_ids", []):
            if runner.status(job_id)["status"] == "running":
                return PlainTextResponse(
                    "a job is still running; wait for it to finish",
                    status_code=409,
                    headers={"Cache-Control": "no-store"},
                )

        request.app.state.finish_shutdown = True
        return templates.TemplateResponse(
            request,
            "done.html",
            {
                "abort": False,
                "message": "Setup finished; you can close this window.",
            },
        )

    @app.get("/done", response_class=HTMLResponse, name="done")
    async def done(request: Request):
        return templates.TemplateResponse(
            request,
            "done.html",
            {
                "abort": False,
                "message": "Your operator configuration has been written.",
            },
        )

    @app.post("/abort", response_class=HTMLResponse, name="abort")
    async def abort_(request: Request):
        runner = request.app.state.runner
        sess = request.state.session
        for job_id in sess.setdefault("job_ids", []):
            if runner.status(job_id)["status"] == "running":
                return PlainTextResponse(
                    "a job is still running; wait for it or cancel it",
                    status_code=409,
                    headers={"Cache-Control": "no-store"},
                )

        request.app.state.finish_shutdown = True
        return templates.TemplateResponse(
            request,
            "done.html",
            {
                "abort": True,
                "message": (
                    "Acknowledgement not given; aborting. No configuration was written."
                ),
            },
        )

    @app.get("/static/{path:path}", name="static")
    async def static_(request: Request, path: str):
        static_dir = request.app.state.setup.static_dir
        target = (static_dir / path).resolve()
        try:
            target.relative_to(static_dir.resolve())
        except ValueError:
            return PlainTextResponse("not found", status_code=404)
        if not target.exists() or not target.is_file():
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(target)

    @app.get("/setup-static/setup.css", name="setup_css")
    async def setup_css(request: Request):
        target = Path(__file__).parent / "static" / "setup.css"
        return FileResponse(target, media_type="text/css")

    return app


def _bind_socket(host: str, port: int) -> tuple[socket.socket, int]:
    """Bind a loopback socket and return it with the actual port."""
    family = socket.AF_INET6 if host == "::1" else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        actual_port = sock.getsockname()[1]
        sock.listen()
        return sock, actual_port
    except Exception:
        sock.close()
        raise


def _display_host(host: str) -> str:
    """Return the host portion to use in a URL."""
    return f"[{host}]" if ":" in host else host


def serve(
    host: str,
    port: int,
    *,
    app: FastAPI | None = None,
    setup_token: str | None = None,
    on_ready: Callable[[str], None] | None = None,
    **create_app_kwargs,
) -> None:
    """Run the setup server on a loopback address only.

    ``port=0`` selects a free port.  Uvicorn is used programmatically, the
    same way Nexus does.  The server stops itself on finish or idle timeout.

    If ``on_ready`` is given, the bound socket is passed to uvicorn so the
    selected port cannot be lost to a race; the callback receives the final
    URL (including ``setup_token``).
    """
    if host not in ("127.0.0.1", "::1"):
        raise ValueError(
            f"setup server must bind to a loopback address (127.0.0.1 or ::1), got {host!r}"
        )

    if app is None:
        app = create_setup_app(**create_app_kwargs)

    sock, actual_port = _bind_socket(host, port)
    app.state.port = actual_port

    config = uvicorn.Config(
        app,
        host=host,
        port=actual_port,
        loop="asyncio",
        log_level="warning",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    app.state.server = server

    if on_ready is not None:
        if setup_token is None:
            setup_token = app.state.setup.store.issue()
        url = (
            f"http://{_display_host(host)}:{actual_port}/"
            f"?token={setup_token}"
        )
        on_ready(url)

    try:
        server.run(sockets=[sock])
    finally:
        try:
            if hasattr(app.state, "runner"):
                app.state.runner.kill_all_sync()
        except Exception:
            logging.exception("error during kill_all_sync")
        try:
            sock.close()
        except OSError:
            pass
