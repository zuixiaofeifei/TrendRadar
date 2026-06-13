"""BrowserSession - 远程 Chrome 单例管理

设计目标:
- 单例: 全局一个 Playwright + Browser + Context, 跨 tool 调用共享
- 懒连接: MCP server 启动时不连 Chrome, 第一次 browser_* tool 调用时连
- 自动重连: 连接断了 (Chrome 重启) 自动重建
- 多 tab: 跟踪当前 active page, 支持 list_tabs/find_tab 切换
- @e refs: snapshot 时往 DOM 里注入 data-mcp-ref="eN" 属性,
          click(@e3) 自动翻译为 [data-mcp-ref="e3"] 选择器,
          抗 CSS hash 类名变化

走的是 trendradar-chrome 容器, 通过 nginx 反代 (改写 Host) 接 CDP.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


def _chrome_host() -> str:
    return os.getenv("CHROME_HOST", "trendradar-chrome")


def _chrome_port() -> int:
    return int(os.getenv("CHROME_PORT", "9222"))


class BrowserSession:
    """全局单例: 一个 MCP server 进程内只有一个"""

    _instance: Optional["BrowserSession"] = None

    @classmethod
    def get(cls) -> "BrowserSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._p = None  # async_playwright instance
        self._browser = None  # CDPBrowser
        self._context = None  # BrowserContext (默认 contexts[0])
        self._active = None  # 当前 active Page

    # ── connection lifecycle ────────────────────────────────

    async def _resolve_ws_url(self) -> str:
        """从 nginx 拿 webSocketDebuggerUrl, 改写 host 为可达地址"""
        host = _chrome_host()
        port = _chrome_port()
        url = f"http://{host}:{port}/json/version"
        # requests 是同步的, 用 to_thread 包一下
        resp = await asyncio.to_thread(requests.get, url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()["webSocketDebuggerUrl"]
        return re.sub(r"^ws://[^/]+", f"ws://{host}:{port}", raw)

    async def _ensure_connected(self) -> None:
        # 已经连上且活着 → 直接返回
        if self._browser is not None and self._browser.is_connected():
            return

        # 启动 playwright (只启一次)
        if self._p is None:
            from playwright.async_api import async_playwright

            self._p = await async_playwright().start()

        # (重新)连 CDP
        logger.info("BrowserSession: 连接 CDP...")
        ws_url = await self._resolve_ws_url()
        self._browser = await self._p.chromium.connect_over_cdp(ws_url)
        self._context = (
            self._browser.contexts[0]
            if self._browser.contexts
            else await self._browser.new_context()
        )
        # active page 失效, 下次 get_page 会重选
        self._active = None
        logger.info(f"BrowserSession: 连接成功, contexts[0] 有 {len(self._context.pages)} 个 page")

    # ── page management ─────────────────────────────────────

    async def get_page(self):
        """拿当前 active page; 没有就用 contexts[0].pages[0], 还没有就新建"""
        await self._ensure_connected()

        # active page 活着 → 直接用
        if self._active is not None and not self._active.is_closed():
            return self._active

        # 复用现有 page
        pages = self._context.pages
        if pages:
            self._active = pages[0]
        else:
            self._active = await self._context.new_page()
        return self._active

    async def new_page(self):
        """开新 page, 设为 active"""
        await self._ensure_connected()
        self._active = await self._context.new_page()
        return self._active

    async def all_pages(self) -> list:
        await self._ensure_connected()
        return list(self._context.pages)

    async def set_active(self, page) -> None:
        self._active = page

    async def find_page_by_url(self, url_pattern: str):
        """找 URL 包含 url_pattern 子串的 page (找到的第一个)"""
        for p in await self.all_pages():
            if url_pattern in p.url:
                return p
        return None

    # ── @e ref system ───────────────────────────────────────

    REF_ASSIGN_JS = r"""
    (() => {
        // 清旧 refs
        document.querySelectorAll('[data-mcp-ref]').forEach(el => {
            el.removeAttribute('data-mcp-ref');
        });

        const SELECTOR = [
            'button', 'a[href]', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="textbox"]',
            '[role="checkbox"]', '[role="radio"]', '[role="tab"]',
            '[role="menuitem"]', '[role="option"]',
            '[contenteditable="true"]', '[contenteditable=""]',
            '[onclick]',
        ].join(',');

        const els = Array.from(document.querySelectorAll(SELECTOR));
        const result = [];
        let i = 0;
        for (const el of els) {
            const rect = el.getBoundingClientRect();
            // 跳过完全不可见的 (但保留 a 标签因为它可能在屏幕外但可滚动到)
            const visible = rect.width > 0 && rect.height > 0;
            if (!visible && el.tagName !== 'A') continue;

            i++;
            const ref = `e${i}`;
            el.setAttribute('data-mcp-ref', ref);

            let name = '';
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                name = el.value || el.placeholder || el.name || '';
            } else if (el.tagName === 'A') {
                name = (el.textContent || el.title || el.getAttribute('aria-label') || '').trim();
            } else if (el.tagName === 'IMG') {
                name = el.alt || '';
            } else {
                name = (el.textContent || el.getAttribute('aria-label') || el.title || '').trim();
            }
            name = name.slice(0, 120).replace(/\s+/g, ' ');

            result.push({
                ref,
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || '',
                type: el.getAttribute('type') || '',
                name,
                href: el.tagName === 'A' ? (el.href || '') : '',
                visible,
            });
        }
        return result;
    })()
    """

    async def assign_refs(self) -> list[dict[str, Any]]:
        """在当前 page DOM 里给所有交互元素注入 data-mcp-ref 属性,
        返回扁平列表 [{ref, tag, role, name, ...}, ...]"""
        page = await self.get_page()
        return await page.evaluate(self.REF_ASSIGN_JS)

    def resolve_selector(self, sel: str) -> str:
        """@eN → [data-mcp-ref="eN"], 其他选择器原样返回"""
        if sel.startswith("@e"):
            ref = sel[1:]
            return f'[data-mcp-ref="{ref}"]'
        return sel
