#!/usr/bin/env python3
"""Mundus LEAP shim — the bridge between a Firestorm/OpenSim viewer and KAINE.

The (forked) viewer launches this as a child process via
``firestorm --leap "python3 .../mundus_leap.py"`` and pipes LEAP protocol
(length-prefixed LLSD on stdin/stdout). The shim drives the avatar and reads
the world on behalf of a KAINE entity embodied as that avatar.

It speaks stock LEAP for everything except vision: control via the ``LLAgent``
and ``LLChatBar`` event APIs, symbolic perception via ``getNearbyAvatarsList`` /
``getNearbyObjectsList`` / ``getPosition``, and — using the op added by our
Firestorm fork — first-person RGB frames via ``LLViewerWindow.captureFrame``.

``MUNDUS_MODE``:
  demo   (default) — scripted self-test against a live grid; proves control,
                     symbolic perception, and vision end-to-end. Artifacts +
                     log land under ``MUNDUS_STATE_DIR`` (default state/mundus).
  bridge           — relay frames/intents to the KAINE Mundus module over a
                     length-prefixed-MessagePack TCP bridge (v2; stub here).

This file is intentionally dependency-light: it uses the ``leap`` reference lib
for the wire protocol and ``llsd`` for payloads. No KAINE imports — the shim is
a separate process and stays decoupled from the cognitive loop.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import leap

STATE_DIR = Path(os.environ.get("MUNDUS_STATE_DIR", "state/mundus"))
MODE = os.environ.get("MUNDUS_MODE", "demo")


def log(*args: object) -> None:
    # The viewer captures the plugin's stderr into its own log; also mirror to
    # a file so we can read it after the fact.
    msg = "[mundus-leap] " + " ".join(str(a) for a in args)
    print(msg, file=sys.stderr, flush=True)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with (STATE_DIR / "shim.log").open("a") as fh:
            fh.write(f"{time.time():.3f} {msg}\n")
    except OSError:
        # The mirror-to-file is a convenience; stderr (captured by the
        # viewer) already has the message, so a disk/permissions issue
        # writing the log file shouldn't crash the shim.
        pass


def request(pump: str, op: str, timeout: float = 15.0, **args: object) -> dict:
    """Invoke ``op`` on the named event-API ``pump`` and return its reply.

    Synchronous: sends with a unique reqid + our reply pump, then reads stdin
    until the matching reply arrives. Unsolicited events seen in the meantime
    are logged and dropped (the v2 bridge mode will route them instead).
    """
    reqid = str(uuid.uuid4())
    leap.send(pump, dict(args, op=op, reqid=reqid, reply=leap.replypump()))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = leap.get()
        data = msg.get("data", {}) if isinstance(msg, dict) else {}
        if isinstance(data, dict) and data.get("reqid") == reqid:
            return data
        log("event (dropped in demo):", _short(msg))
    raise TimeoutError(f"{pump}.{op} timed out after {timeout}s")


def _short(obj: object, n: int = 200) -> str:
    s = repr(obj)
    return s if len(s) <= n else s[:n] + f"... (+{len(s) - n})"


def wait_until_in_world(timeout: float = 180.0) -> dict:
    """Poll until the avatar is actually in a region (login complete)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            pos = request("LLAgent", "getPosition", timeout=8.0)
            if pos.get("region") or pos.get("global") or pos.get("position"):
                return pos
        except TimeoutError:
            # Expected before login/region-entry completes: getPosition has
            # nothing to reply with yet. Keep polling until the outer
            # deadline expires.
            pass
        log("waiting for login / region ...")
        time.sleep(3.0)
    raise TimeoutError("never reached in-world state")


def save_frame(frame: dict) -> str | None:
    """Write a captureFrame reply (RGB bytes) to a PPM so vision is verifiable."""
    if not frame.get("ok"):
        log("captureFrame not ok:", _short(frame))
        return None
    w, h = int(frame.get("width", 0)), int(frame.get("height", 0))
    data = frame.get("data")
    if isinstance(data, str):
        data = data.encode("latin-1")
    if not data or w <= 0 or h <= 0:
        log("captureFrame returned no usable data:", w, h, type(data).__name__)
        return None
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out = STATE_DIR / "frame_0.ppm"
    with out.open("wb") as fh:
        fh.write(f"P6\n{w} {h}\n255\n".encode())
        fh.write(bytes(data)[: w * h * 3])
    log(f"vision: wrote {w}x{h} frame ({len(data)} bytes) -> {out}")
    return str(out)


# Viewer settings for KAINE's embodiment viewer: HIGH visual fidelity so the
# avatar perceives a fully fleshed-out world (operator now runs their own
# viewer on the grid host, so this box runs only KAINE's viewer — the GPU
# budget is there for quality). Immersion bits stay: no UI chrome/sounds, and
# captured frames exclude the interface. Applied via LLViewerControl on bind;
# set-and-ignore so an unknown key (names vary by build) never breaks the shim.
# NOTE: exact keys/types want a live confirm against this build.
VIEWER_SETTINGS: dict[str, object] = {
    # --- immersion (kept lean: chrome/sounds add nothing to perception) ---
    "AudioLevelUI": 0.0,            # no UI click/notification sounds
    "RenderUIInSnapshot": False,    # captured frames exclude the interface
    # --- visual fidelity: high, for a rich scene the vision feed can read --
    "RenderShadowDetail": 2,        # full sun/moon + projector shadows
    "RenderFSAASamples": 2,         # antialiasing on (smooth edges)
    "RenderDeferredSSAO": True,     # ambient occlusion (depth/contact cues)
    "RenderReflectionDetail": 3,    # water/mirror reflections
    "RenderDepthOfField": False,    # off: blur would degrade DINOv2 input
    "RenderGlow": True,             # bloom (part of the rendered look)
    "RenderMaxPartCount": 4096,     # rich particle effects
    "RenderVolumeLODFactor": 3.0,   # high object/mesh detail
    "RenderFarClip": 512.0,         # long draw distance — see the wider world
    "RenderAvatarMaxComplexity": 0, # 0 = unlimited; never imposter nearby avatars
    # --- in-world web/media autoplay off (heavy CEF, marginal for vision) --
    "AudioStreamingMedia": False,
    "AudioStreamingMusic": False,
    "ParcelMediaAutoPlayEnable": False,
    "MediaTentativeAutoPlay": False,
}


def apply_viewer_settings(req) -> None:
    """Push VIEWER_SETTINGS via LLViewerControl.set, tolerating unknown keys.
    `req(pump, op, **args)` is the mode's request fn (demo or bridge)."""
    ok = 0
    for key, value in VIEWER_SETTINGS.items():
        try:
            req("LLViewerControl", "set", timeout=8.0,
                group="Global", key=key, value=value)
            ok += 1
        except Exception as exc:
            log(f"setting {key} not applied ({exc})")
    log(f"viewer settings applied: {ok}/{len(VIEWER_SETTINGS)}")
    # Mouselook (first-person) + UI-hide are camera/UI modes, not settings; the
    # vision feed already excludes UI via captureFrame(show_ui=false). Locking
    # mouselook is tracked as a small viewer-side follow-up.


def run_demo() -> None:
    log("handshake: reply=", leap.replypump(), "cmd=", leap.cmdpump())
    apply_viewer_settings(request)

    # 1. Discover the callable surface (sanity that LEAP is wired).
    try:
        apis = request(leap.cmdpump(), "getAPIs", timeout=10.0)
        names = sorted((apis.get("data") or apis).keys()) if isinstance(apis, dict) else []
        log("APIs available:", ", ".join(n for n in names if isinstance(n, str))[:300])
    except Exception as exc:
        log("getAPIs failed (continuing):", exc)

    # 2. Wait for login to land us in a region.
    pos = wait_until_in_world()
    log("in-world. position reply:", _short(pos))

    # 3. Symbolic perception.
    for op in ("getNearbyAvatarsList", "getNearbyObjectsList"):
        try:
            log(op, "->", _short(request("LLAgent", op, timeout=10.0)))
        except Exception as exc:
            log(op, "failed:", exc)

    # 4. Speak in local chat (proves the action path out).
    try:
        request("LLChatBar", "sendChat",
                message="Kaine here — first embodied words. Testing the bridge.",
                channel=0, type="normal", timeout=10.0)
        log("sent local chat")
    except Exception as exc:
        log("sendChat failed:", exc)

    # 5. Vision: grab a first-person frame via our forked captureFrame op.
    try:
        save_frame(request("LLViewerWindow", "captureFrame",
                           width=224, height=224, timeout=20.0))
    except Exception as exc:
        log("captureFrame failed:", exc)

    # 6. Move: autopilot a few metres along the current heading.
    try:
        g = pos.get("global") or pos.get("position")
        if isinstance(g, (list, tuple)) and len(g) >= 3:
            target = [float(g[0]) + 3.0, float(g[1]) + 3.0, float(g[2])]
            request("LLAgent", "startAutoPilot", target_global=target,
                    allow_flying=False, timeout=10.0)
            log("autopilot started toward", target)
    except Exception as exc:
        log("startAutoPilot failed:", exc)

    # 7. Idle perception loop until the viewer shuts the plugin down.
    log("demo steps done; entering idle perception loop")
    while True:
        time.sleep(5.0)
        try:
            log("pos:", _short(request("LLAgent", "getPosition", timeout=8.0), 120))
        except Exception as exc:
            log("perception poll failed:", exc)


# ---------------------------------------------------------------------------
# Bridge mode — relay between LEAP (the viewer) and the KAINE Mundus module.
# Uses eventlet green threads because the `leap` lib is eventlet-based: one
# reader drains LEAP and routes op-replies (by reqid) vs unsolicited events,
# while other greenlets poll perception and dispatch action frames. The wire to
# Mundus is the same length-prefixed MessagePack contract Mundus speaks.
# ---------------------------------------------------------------------------
import struct as _struct

import msgpack as _msgpack

BRIDGE_HOST = os.environ.get("MUNDUS_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("MUNDUS_BRIDGE_PORT", "7781"))
POLL_INTERVAL = float(os.environ.get("MUNDUS_POLL_INTERVAL", "2.0"))
VISION = os.environ.get("MUNDUS_VISION") == "1"


def _m_say(p):
    return ("LLChatBar", "sendChat", {"message": p.get("message", ""),
            "channel": p.get("channel", 0), "type": p.get("type", "normal")})


def _m_move(p):
    tgt = p.get("to") or p.get("target_global")
    return ("LLAgent", "startAutoPilot",
            {"target_global": tgt, "allow_flying": bool(p.get("allow_flying", False))}) if tgt else None


def _m_turn(p):
    la = p.get("look_at")
    return ("LLAgent", "lookAt", {"position": la}) if la else None


def _m_teleport(p):
    return ("LLAgent", "requestTeleport",
            {"regionname": p.get("region") or p.get("regionname"),
             "x": p.get("x"), "y": p.get("y"), "z": p.get("z")})


def _m_sit(p):     return ("LLAgent", "requestSit", {"obj_uuid": p.get("obj_uuid")})
def _m_stand(p):   return ("LLAgent", "requestStand", {})
def _m_touch(p):   return ("LLAgent", "requestTouch", {"obj_uuid": p.get("obj_uuid")})
def _m_animate(p): return ("LLAgent", "playAnimation",
                           {"item_id": p.get("anim") or p.get("item_id"),
                            "inworld": bool(p.get("inworld", True))})
def _m_gesture(p): return ("LLGesture", "startGesture", {"id": p.get("id")})

_ACTION_MAP = {"say": _m_say, "move": _m_move, "turn": _m_turn,
               "teleport": _m_teleport, "sit_on": _m_sit, "stand": _m_stand,
               "touch": _m_touch, "animate": _m_animate, "gesture": _m_gesture}


class BridgeRunner:
    def __init__(self):
        import eventlet
        from eventlet.green import socket as green_socket
        from eventlet.queue import Queue
        from eventlet.semaphore import Semaphore
        self._eventlet = eventlet
        self._Queue = Queue
        self._pending: dict[str, object] = {}
        self._send_lock = Semaphore(1)
        self._sock = None
        last = None
        for attempt in range(20):  # tolerate KAINE/Mundus not being up yet
            try:
                s = green_socket.socket()
                s.connect((BRIDGE_HOST, BRIDGE_PORT))
                self._sock = s
                break
            except OSError as exc:
                last = exc
                log(f"bridge: Mundus not reachable yet ({exc}); retry {attempt+1}/20")
                eventlet.sleep(3.0)
        if self._sock is None:
            raise ConnectionError(f"could not reach Mundus at {BRIDGE_HOST}:{BRIDGE_PORT}: {last}")
        log(f"bridge: connected to Mundus at {BRIDGE_HOST}:{BRIDGE_PORT}")

    def request(self, pump, op, timeout=15.0, **args):
        reqid = str(uuid.uuid4())
        q = self._Queue()
        self._pending[reqid] = q
        with self._send_lock:
            leap.send(pump, dict(args, op=op, reqid=reqid, reply=leap.replypump()))
        try:
            return q.get(timeout=timeout)
        except Exception:
            self._pending.pop(reqid, None)
            raise TimeoutError(f"{pump}.{op} timed out")

    def _leap_reader(self):
        while True:
            try:
                msg = leap.get()
            except leap.ViewerShutdown:
                log("bridge: viewer shutdown"); return
            data = msg.get("data", {}) if isinstance(msg, dict) else {}
            reqid = data.get("reqid") if isinstance(data, dict) else None
            q = self._pending.pop(reqid, None) if reqid else None
            if q is not None:
                q.put(data)
            else:
                self._forward_event(msg)

    def _forward_event(self, msg):
        # Unsolicited LEAP events. Inbound local chat lands here IF the viewer
        # publishes it to a listenable pump (shape TBD live; may need fork
        # "Patch B"). Forward anything chat-like.
        data = msg.get("data", {}) if isinstance(msg, dict) else {}
        if not isinstance(data, dict):
            return
        text = data.get("message") or data.get("chat") or data.get("text")
        if text and "reqid" not in data:
            self.send_frame({"kind": "chat",
                             "from_name": data.get("from_name") or data.get("from"),
                             "from_id": data.get("from_id") or data.get("source_id"),
                             "message": str(text), "channel": data.get("channel", 0)})

    def send_frame(self, obj):
        body = _msgpack.packb(obj, use_bin_type=True)
        with self._send_lock:
            self._sock.sendall(_struct.pack(">I", len(body)) + body)

    def _recvall(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("bridge closed")
            buf += chunk
        return buf

    def _bridge_reader(self):
        while True:
            try:
                (length,) = _struct.unpack(">I", self._recvall(4))
                frame = _msgpack.unpackb(self._recvall(length), raw=False)
            except Exception as exc:
                log("bridge: read ended:", exc); return
            if isinstance(frame, dict) and frame.get("kind") == "action":
                self._dispatch_action(frame)

    def _dispatch_action(self, frame):
        action = frame.get("action")
        mapper = _ACTION_MAP.get(action)
        if mapper is None:
            log("bridge: unknown action", action); return
        spec = mapper(frame)
        if spec is None:
            log("bridge: action", action, "missing params"); return
        pump, op, args = spec
        try:
            self.request(pump, op, timeout=10.0, **args)
            self.send_frame({"kind": "action_result", "action": action, "ok": True})
        except Exception as exc:
            self.send_frame({"kind": "action_result", "action": action,
                             "ok": False, "reason": str(exc)})

    def _perception_poll(self):
        while True:
            self._eventlet.sleep(POLL_INTERVAL)
            try:
                pos = self.request("LLAgent", "getPosition", timeout=8.0)
                self.send_frame({"kind": "proprio",
                                 **{k: v for k, v in pos.items() if k != "reqid"}})
            except Exception as exc:
                log("poll getPosition:", exc); continue
            for op, kind, key in (("getNearbyAvatarsList", "entity", "avatars"),
                                  ("getNearbyObjectsList", "scene", "objects")):
                try:
                    r = self.request("LLAgent", op, timeout=8.0)
                    self.send_frame({"kind": kind, key: r.get(key, r)})
                except Exception as exc:
                    log("poll", op, ":", exc)
            if VISION:
                try:
                    f = self.request("LLViewerWindow", "captureFrame",
                                     timeout=15.0, width=224, height=224)
                    # bytes go to a future Topos side channel; metadata only here
                    self.send_frame({"kind": "frame", "w": f.get("width"),
                                     "h": f.get("height"),
                                     "encoding": f.get("encoding", "rgb8")})
                except Exception as exc:
                    log("poll captureFrame:", exc)

    def run(self):
        et = self._eventlet
        et.spawn(self._leap_reader)
        et.sleep(0.5)  # let the LEAP reader start so request replies route
        apply_viewer_settings(self.request)
        et.spawn(self._bridge_reader)
        et.spawn(self._perception_poll)
        log("bridge: relays running (leap-reader, bridge-reader, perception-poll)")
        while True:
            et.sleep(3600)


def run_bridge():
    BridgeRunner().run()


def main() -> None:
    leap.__init__()  # consume the viewer's intro message (sets reply/cmd pumps)
    log(f"mundus-leap up, MODE={MODE}")
    try:
        if MODE == "bridge":
            run_bridge()
        else:
            run_demo()
    except leap.ViewerShutdown:
        log("viewer shut the plugin down; exiting")
    except Exception as exc:  # never crash silently inside the viewer
        log("FATAL:", repr(exc))
        raise


if __name__ == "__main__":
    main()
