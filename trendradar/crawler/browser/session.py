"""Chrome 会话管理 — 通过 CDP 连接 trendradar-chrome 容器

依赖 docker-compose 的 trendradar-chrome 服务 (Chrome on Xvfb).
所有页面操作走 Playwright connect_over_cdp, 登录态 cookies 持久化在
chrome-data volume, 容器重启不丢.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


def _chrome_host() -> str:
    return os.getenv("CHROME_HOST", "trendradar-chrome")


def _chrome_port() -> int:
    return int(os.getenv("CHROME_PORT", "9222"))


def cdp_url() -> str:
    """返回 CDP HTTP 根 URL, 如 http://trendradar-chrome:9222"""
    return f"http://{_chrome_host()}:{_chrome_port()}"


def health_check(timeout: float = 5.0) -> Optional[dict]:
    """检查 Chrome CDP 是否响应, 返回 Browser 信息或 None"""
    import requests

    try:
        r = requests.get(f"{cdp_url()}/json/version", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Chrome CDP 不可达 ({cdp_url()}): {e}")
        return None


@contextmanager
def browser_page(
    url: Optional[str] = None,
    *,
    timeout_ms: int = 30000,
    wait_until: str = "domcontentloaded",
) -> Iterator:
    """打开一个新 tab, 上下文管理器结束时自动 close

    复用 contexts[0], 让登录态 cookies 一直存活在 --user-data-dir 里.

    Usage:
        with browser_page("https://m.okjike.com/") as page:
            print(page.title())
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url())
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            if url:
                page.goto(url, wait_until=wait_until)
            yield page
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
