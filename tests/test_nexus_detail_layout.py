# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import pytest

from kaine.nexus.config import NexusConfig
from tests.test_nexus_routers import _make_client


class _TallHealth:
    cache_ttl_s = 30.0

    async def snapshot(self):
        return {
            "dependencies": [
                {
                    "name": f"Service {i}",
                    "role": "role",
                    "status": "up",
                    "detail": "a detail line long enough to wrap in a narrow column " * 2,
                    "checked_at": "2026-10-02T00:00:00Z",
                }
                for i in range(16)
            ],
            "modules": [],
        }


@pytest.mark.asyncio
async def test_diagnostics_page_has_no_right_sidebar():
    client, app = await _make_client()
    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/diagnostics/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            assert "rail--right" not in response.text


@pytest.mark.asyncio
async def test_console_page_keeps_right_sidebar():
    client, app = await _make_client()
    async with app.router.lifespan_context(app):
        async with client:
            response = await client.get(
                "/",
                headers={"Authorization": "Bearer test-token"},
            )
            assert response.status_code == 200
            assert "rail--right" in response.text
            assert "board-health" in response.text


@pytest.mark.asyncio
async def test_diagnostics_layout_in_real_browser():
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    browser = None
    async with async_playwright() as pw:
        try:
            try:
                browser = await pw.chromium.launch(channel="chrome")
            except Exception as chrome_err:
                try:
                    browser = await pw.chromium.launch()
                except Exception:
                    pytest.skip(
                        f"System Chrome unavailable and fallback Chromium failed: {chrome_err}"
                    )

            page = await browser.new_page(viewport={"width": 1600, "height": 1000})

            config = NexusConfig(
                host_allowlist=("127.0.0.1", "localhost", "test", "nexus.test"),
            )
            client, app = await _make_client(
                config=config,
                health_prober=_TallHealth(),
            )
            client.base_url = httpx.URL("http://nexus.test")

            async with app.router.lifespan_context(app):
                async with client:

                    async def handler(route):
                        parsed = urlparse(route.request.url)
                        path_and_query = parsed.path + (
                            "?" + parsed.query if parsed.query else ""
                        )
                        if parsed.path.endswith("/stream") or "/stream?" in path_and_query:
                            await route.abort()
                            return
                        resp = await client.request(
                            route.request.method,
                            path_and_query,
                            headers={"Authorization": "Bearer test-token"},
                            content=route.request.post_data_buffer,
                        )
                        await route.fulfill(
                            status=resp.status_code,
                            headers={
                                k: v
                                for k, v in resp.headers.items()
                                if k.lower()
                                not in ("content-length", "content-encoding", "transfer-encoding")
                            },
                            body=resp.content,
                        )

                    await page.route("http://nexus.test/**", handler)

                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))

                    await page.goto("http://nexus.test/diagnostics/")
                    await page.wait_for_load_state("load")

                    data = await page.evaluate(
                        """() => {
                            const pageEl = document.querySelector('.page');
                            const pageRect = pageEl.getBoundingClientRect();
                            const boards = Array.from(document.querySelectorAll('.page > .board')).map(board => {
                                const title = board.querySelector('.board__title');
                                const cards = board.querySelector('.board__cards');
                                const titleRect = title ? title.getBoundingClientRect() : { left: 0, bottom: 0 };
                                const cardsRect = cards ? cards.getBoundingClientRect() : { left: 0, top: 0 };
                                const boardRect = board.getBoundingClientRect();
                                return {
                                    left: boardRect.left,
                                    titleLeft: titleRect.left,
                                    titleBottom: titleRect.bottom,
                                    cardsLeft: cardsRect.left,
                                    cardsTop: cardsRect.top,
                                };
                            });
                            return { pageRight: pageRect.right, boards };
                        }"""
                    )

                    assert len(data["boards"]) >= 3
                    for b in data["boards"]:
                        assert abs(b["titleLeft"] - b["cardsLeft"]) <= 1
                        assert b["cardsTop"] >= b["titleBottom"] - 1
                        assert b["left"] < data["pageRight"]

                    assert errors == []
        finally:
            if browser is not None:
                await browser.close()
