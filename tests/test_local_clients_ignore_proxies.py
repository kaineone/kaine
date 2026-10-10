# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Clients of KAINE's own services never follow proxy settings.

httpx trusts the environment by default, so a set HTTP_PROXY or ALL_PROXY
sends even a loopback request to the proxy; urllib's default opener does the
same. KAINE's clients carry the entity's prompts, audio and speech to local
services, so every one of them must ignore the proxy variables. Only
setup-time downloads of public artifacts may use a proxy.
"""

from __future__ import annotations

import ast
import asyncio
import http.server
import json
import pathlib
import threading

from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

REPO = pathlib.Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("kaine", "scripts")

# Files that may follow proxy settings, each because it only fetches public,
# hash-pinned artifacts at setup time and never carries entity data.
ALLOWED_PROXY_CAPABLE = {
    "kaine/setup/speech_models.py": "downloads public speech models at setup",
    "kaine/wheel_index.py": "fetches public wheel indexes at setup",
    "scripts/k1jev/sources.py": "fetches public datasets and the generator GGUF for K1-Jev data builds, each SHA-256-pinned",
}

HTTPX_CALLS = {"Client", "AsyncClient", "get", "post", "put", "patch", "delete", "request", "stream"}


def _is_httpx_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "httpx"
        and func.attr in HTTPX_CALLS
    )


def _keyword_is_constant(node: ast.Call, name: str, value: object) -> bool:
    return any(
        kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is value
        for kw in node.keywords
    )


def _is_websockets_call(node: ast.Call) -> bool:
    """websockets.connect(...) or websockets.<sub>.connect(...): websockets 16
    follows proxy settings unless the client passes proxy=None."""
    func = node.func
    while isinstance(func, ast.Attribute):
        func = func.value
    return isinstance(func, ast.Name) and func.id == "websockets"


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _builds_proxyless_opener(node: ast.Call) -> bool:
    """build_opener(ProxyHandler({})): the one urllib form that ignores proxies."""
    for arg in node.args:
        if (
            isinstance(arg, ast.Call)
            and _call_name(arg) == "ProxyHandler"
            and len(arg.args) == 1
            and isinstance(arg.args[0], ast.Dict)
            and not arg.args[0].keys
        ):
            return True
    return False


def _file_violations(rel: str, source: str) -> list[str]:
    tree = ast.parse(source, filename=rel)
    allowed = rel in ALLOWED_PROXY_CAPABLE
    found: list[str] = []

    for node in ast.walk(tree):
        # Only the plain `import httpx` and `import websockets` forms are
        # scanned below, so the forms that would hide a client from the scan
        # are refused for both libraries.
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "httpx" and alias.asname not in (None, "httpx"):
                    found.append(f"{rel}:{node.lineno} httpx imported under an alias")
                if alias.name == "websockets" and alias.asname not in (None, "websockets"):
                    found.append(f"{rel}:{node.lineno} websockets imported under an alias")
                if alias.name.split(".")[0] == "requests" and not allowed:
                    found.append(f"{rel}:{node.lineno} requests follows proxy settings")
        if isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top == "httpx":
                found.append(f"{rel}:{node.lineno} from-import of httpx (use httpx.<name>)")
            if top == "websockets":
                found.append(f"{rel}:{node.lineno} from-import of websockets (use websockets.<name>)")
            if top == "requests" and not allowed:
                found.append(f"{rel}:{node.lineno} requests follows proxy settings")
        if not isinstance(node, ast.Call):
            continue
        if _is_httpx_call(node):
            # Allowlisted downloaders must say on purpose that they use the
            # environment; everything else must refuse it.
            wanted = True if allowed else False
            if not _keyword_is_constant(node, "trust_env", wanted):
                found.append(f"{rel}:{node.lineno} httpx call without trust_env={wanted}")
        if _call_name(node) == "connect" and _is_websockets_call(node):
            if not _keyword_is_constant(node, "proxy", None):
                found.append(f"{rel}:{node.lineno} websockets connect without proxy=None")
        name = _call_name(node)
        if name == "urlopen" and rel not in ALLOWED_PROXY_CAPABLE:
            found.append(f"{rel}:{node.lineno} urlopen follows proxy settings")
        if name == "build_opener" and rel not in ALLOWED_PROXY_CAPABLE:
            if not _builds_proxyless_opener(node):
                found.append(f"{rel}:{node.lineno} build_opener without ProxyHandler({{}})")

    return found


def _violations() -> list[str]:
    found: list[str] = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            found.extend(_file_violations(rel, path.read_text(encoding="utf-8")))
    return found


def test_every_runtime_http_call_ignores_proxy_settings():
    found = _violations()
    assert not found, "clients that would follow proxy settings:\n" + "\n".join(found)


def test_allowlisted_files_are_named_exactly():
    for rel in ALLOWED_PROXY_CAPABLE:
        assert "*" not in rel and rel.endswith(".py"), rel
        assert (REPO / rel).is_file(), rel


def test_guard_refuses_hidden_import_forms(tmp_path):
    def case(source: str) -> list[str]:
        sample = tmp_path / "sample.py"
        sample.write_text(source, encoding="utf-8")
        return _file_violations("kaine/x.py", sample.read_text(encoding="utf-8"))

    assert case("import httpx as hx\n") == ["kaine/x.py:1 httpx imported under an alias"]
    assert case("from httpx import AsyncClient\n") == [
        "kaine/x.py:1 from-import of httpx (use httpx.<name>)"
    ]
    assert case("import websockets as ws\n") == [
        "kaine/x.py:1 websockets imported under an alias"
    ]
    assert case("from websockets.asyncio.client import connect\n") == [
        "kaine/x.py:1 from-import of websockets (use websockets.<name>)"
    ]
    assert case("import websockets\nwebsockets.connect('ws://x', proxy=None)\n") == []
    assert case("import httpx\nhttpx.AsyncClient(trust_env=False)\n") == []
    assert case("import httpx\nhttpx.AsyncClient()\n") == [
        "kaine/x.py:2 httpx call without trust_env=False"
    ]


def test_lingua_client_reaches_a_local_server_with_a_proxy_set(monkeypatch):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server's method name
            if self.path != "/v1/chat/completions":
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps({"choices": [{"message": {"content": "direct"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    # A proxy that does not exist: following it would fail the request.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    async def run() -> str:
        client = OpenAIChatClient(base_url=f"http://127.0.0.1:{port}/v1", api_key=None, timeout_s=5.0)
        try:
            response = await client.complete(ChatRequest(prompt="hi", model="m", think=False))
            return response.text
        finally:
            await client.aclose()

    try:
        assert asyncio.run(run()) == "direct"
    finally:
        server.shutdown()
        thread.join(timeout=5)
