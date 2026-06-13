"""Browser tools - 通过 trendradar-chrome 接管真 Chrome 给 AI 用

15 个工具, 对齐 Kimi WebBridge 的核心子集.
所有工具都是薄封装, 业务逻辑都在 services/browser_session.py 里.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from ..services.browser_session import BrowserSession, _chrome_host, _chrome_port

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# P0: 必须有的 6 个
# ─────────────────────────────────────────────────────────


async def navigate(
    url: str,
    new_tab: bool = False,
    wait_until: str = "domcontentloaded",
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """打开 URL.

    Args:
        url: 目标 URL
        new_tab: True 开新 tab 并设为 active, False 用当前 tab 跳转 (默认)
        wait_until: 等待时机 - "load" / "domcontentloaded" / "networkidle"
        timeout_ms: 超时 (默认 30s)

    Returns: {success, url, title}
    """
    session = BrowserSession.get()
    page = await session.new_page() if new_tab else await session.get_page()
    await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
    return {
        "success": True,
        "url": page.url,
        "title": await page.title(),
        "new_tab": new_tab,
    }


async def snapshot() -> dict[str, Any]:
    """获取当前页面的可交互元素列表 (带 @e refs).

    每个元素带一个唯一 ref 如 e1, e2... 后续 click/fill 用 "@e3" 即可,
    不用关心 CSS 类名 hash 变化.

    Returns: {url, title, elements: [{ref, tag, role, name, ...}, ...]}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    elements = await session.assign_refs()
    return {
        "url": page.url,
        "title": await page.title(),
        "element_count": len(elements),
        "elements": elements,
    }


async def click(selector: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """点击元素. selector 支持 @eN (snapshot 的 ref) 或标准 CSS.

    Args:
        selector: "@e3" 或 "button.submit" 之类
        timeout_ms: 等待元素出现的超时 (默认 10s)

    Returns: {success, selector_resolved, tag, text}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    resolved = session.resolve_selector(selector)
    locator = page.locator(resolved).first
    await locator.wait_for(state="visible", timeout=timeout_ms)
    tag = await locator.evaluate("el => el.tagName")
    text = await locator.text_content() or ""
    await locator.click(timeout=timeout_ms)
    return {
        "success": True,
        "selector": selector,
        "selector_resolved": resolved,
        "tag": tag,
        "text": text[:80],
    }


async def screenshot(
    selector: Optional[str] = None,
    full_page: bool = False,
    label: str = "screenshot",
) -> dict[str, Any]:
    """截图 → 存到 /app/output/qr/, 返回 public URL.

    Args:
        selector: 指定元素截图 (如 "@e3" 或 "[class*=qrCodeContainer]"); None=整页
        full_page: 截全长 (含滚动部分), 仅在 selector=None 时有效
        label: 文件名标签, 默认 "screenshot" → screenshot-{ts}.png

    Returns: {success, path, public_url, size_bytes}
    """
    session = BrowserSession.get()
    page = await session.get_page()

    out_dir = Path("/app/output/qr")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    # 文件名清洗
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
    out_path = out_dir / f"{safe_label}-{ts}.png"

    if selector:
        resolved = session.resolve_selector(selector)
        await page.locator(resolved).first.screenshot(path=str(out_path))
    else:
        await page.screenshot(path=str(out_path), full_page=full_page)

    size = out_path.stat().st_size

    public_host = os.getenv("PUBLIC_HOST", "").strip()
    webserver_port = os.getenv("WEBSERVER_PORT", "8080")
    if public_host:
        public_url = f"http://{public_host}:{webserver_port}/qr/{out_path.name}"
    else:
        public_url = None

    return {
        "success": True,
        "path": str(out_path),
        "public_url": public_url,
        "size_bytes": size,
    }


async def evaluate(code: str) -> dict[str, Any]:
    """在当前页面跑 JS, 返回结果 (必须 JSON 可序列化).

    Args:
        code: JS 代码, 用 IIFE 包一下避免污染全局: "(() => {{ return ... }})()"
              支持 async/await: "async () => {{ await ...; return ...; }}"

    Returns: {success, value, type}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    value = await page.evaluate(code)
    return {
        "success": True,
        "type": type(value).__name__,
        "value": value,
    }


async def push_qr_to_feishu(
    selector: str,
    label: str = "扫码",
    expire_minutes: int = 3,
) -> dict[str, Any]:
    """截 QR 元素 → 存到 output/qr/ → 推飞书带 URL.

    手机扫码登录的核心工具. 完整流程:
        1. navigate(站点登录页)
        2. snapshot() 找到 QR 元素 (类似 "[class*=qrCode]")
        3. push_qr_to_feishu("[class*=qrCodeContainer]", label="即刻")
           → 飞书收到一条带链接的卡片
        4. 你手机点链接 → 看到 QR → App 扫码
        5. 循环 wait_for(登录后的特征元素) 等扫码完成

    Args:
        selector: QR 元素选择器 (@eN 或 CSS)
        label: 飞书消息标题里的站点名, 如 "即刻" / "知乎"
        expire_minutes: 卡片显示的有效期 (仅文案, 不真过期)

    Returns: {success, qr_path, public_url, feishu_sent}
    """
    session = BrowserSession.get()
    page = await session.get_page()

    # 1. 截 QR
    out_dir = Path("/app/output/qr")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40] or "qr"
    qr_path = out_dir / f"{safe_label}-{ts}.png"

    resolved = session.resolve_selector(selector)
    await page.locator(resolved).first.screenshot(path=str(qr_path))

    # 2. 推飞书 (复用 trendradar.crawler.browser.notify)
    feishu_sent = False
    public_url = None
    try:
        from trendradar.crawler.browser.notify import push_qr, _public_qr_url

        feishu_sent = push_qr(safe_label, qr_path, expire_minutes=expire_minutes)
        public_url = _public_qr_url(qr_path)
    except Exception as e:
        logger.error(f"推飞书失败: {e}")

    return {
        "success": True,
        "qr_path": str(qr_path),
        "public_url": public_url,
        "feishu_sent": feishu_sent,
        "label": label,
        "hint": "等用户扫码后,用 browser_wait_for 等登录后特征元素出现 (timeout 120000)",
    }


# ─────────────────────────────────────────────────────────
# P1: 强需求 5 个
# ─────────────────────────────────────────────────────────


async def fill(selector: str, value: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """填写 input/textarea 或 contenteditable. 会清空原值再填入.

    Args:
        selector: @eN 或 CSS
        value: 新值
        timeout_ms: 等元素超时

    Returns: {success, mode} mode=value(标准 input) | contenteditable
    """
    session = BrowserSession.get()
    page = await session.get_page()
    resolved = session.resolve_selector(selector)
    locator = page.locator(resolved).first
    await locator.wait_for(state="visible", timeout=timeout_ms)

    # 判断是 input/textarea 还是 contenteditable
    tag = (await locator.evaluate("el => el.tagName")).lower()
    is_contenteditable = await locator.evaluate("el => el.isContentEditable === true")

    if is_contenteditable:
        await locator.click()
        await locator.evaluate("el => { el.focus(); document.execCommand('selectAll'); }")
        await page.keyboard.type(value)
        mode = "contenteditable"
    elif tag in ("input", "textarea"):
        await locator.fill(value)
        mode = "value"
    else:
        await locator.fill(value)  # try anyway
        mode = "fallback"

    return {"success": True, "selector": selector, "mode": mode, "tag": tag}


async def wait_for(
    selector: str,
    state: str = "visible",
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """等元素出现 / 消失. 适合等 SPA 渲染 + 等用户扫码完成.

    Args:
        selector: @eN 或 CSS
        state: "visible" (默认) / "hidden" / "attached" / "detached"
        timeout_ms: 超时 (默认 30s, 扫码场景给 120000 = 2 分钟)

    Returns: {success, selector, state, found}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    resolved = session.resolve_selector(selector)
    try:
        await page.locator(resolved).first.wait_for(state=state, timeout=timeout_ms)
        return {"success": True, "selector": selector, "state": state, "found": True}
    except Exception as e:
        return {
            "success": False,
            "selector": selector,
            "state": state,
            "found": False,
            "error": str(e)[:120],
        }


async def list_tabs() -> dict[str, Any]:
    """列出所有 tab. is_active=True 表示当前 active page (后续操作的对象).

    Returns: {tabs: [{index, url, title, is_active}]}
    """
    session = BrowserSession.get()
    pages = await session.all_pages()
    active = await session.get_page()
    tabs = []
    for i, p in enumerate(pages):
        tabs.append(
            {
                "index": i,
                "url": p.url,
                "title": await p.title(),
                "is_active": p is active,
            }
        )
    return {"count": len(tabs), "tabs": tabs}


async def find_tab(url_pattern: str) -> dict[str, Any]:
    """找 URL 含 url_pattern 子串的 tab, 设为 active. 找不到返回 success=False.

    Args:
        url_pattern: 子串匹配, 如 "web.okjike.com" 或 "/timeline"

    Returns: {success, url, title, index}
    """
    session = BrowserSession.get()
    p = await session.find_page_by_url(url_pattern)
    if not p:
        return {"success": False, "error": f"no tab url contains {url_pattern!r}"}
    await session.set_active(p)
    pages = await session.all_pages()
    return {
        "success": True,
        "url": p.url,
        "title": await p.title(),
        "index": pages.index(p),
    }


async def close_tab() -> dict[str, Any]:
    """关 active tab. 如果是最后一个, 自动新建一个空白 tab 占位.

    Returns: {success, closed_url}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    closed_url = page.url
    await page.close()
    session._active = None  # 下次 get_page 自动选新的
    # 确保还有 page 可用
    pages = await session.all_pages()
    if not pages:
        await session.new_page()
    return {"success": True, "closed_url": closed_url}


# ─────────────────────────────────────────────────────────
# P2: 调试/查询 4 个
# ─────────────────────────────────────────────────────────


async def get_url() -> dict[str, Any]:
    """当前 page URL + title (判断登录态最常用)."""
    session = BrowserSession.get()
    page = await session.get_page()
    return {"url": page.url, "title": await page.title()}


async def get_html(selector: Optional[str] = None, max_chars: int = 100000) -> dict[str, Any]:
    """拿当前页 outerHTML (或指定元素).

    ⚠️ 全页 HTML 可能几 MB, 大幅消耗 token. 用前先 snapshot 看下,
    通常不需要直接读 HTML.

    Args:
        selector: 指定元素 (@eN 或 CSS); None=整页 documentElement
        max_chars: 截断长度防爆 token (默认 100000 ≈ 30000 中文字)

    Returns: {html, truncated, original_length}
    """
    session = BrowserSession.get()
    page = await session.get_page()
    if selector:
        resolved = session.resolve_selector(selector)
        html = await page.locator(resolved).first.evaluate("el => el.outerHTML")
    else:
        html = await page.evaluate("() => document.documentElement.outerHTML")
    original_length = len(html)
    truncated = original_length > max_chars
    return {
        "html": html[:max_chars],
        "truncated": truncated,
        "original_length": original_length,
    }


async def get_cookies(url_pattern: Optional[str] = None) -> dict[str, Any]:
    """看 cookies (判断登录态用). 不返回 value, 只返回名称和域 (避免泄露).

    Args:
        url_pattern: 子串 url 过滤; None 返回所有

    Returns: {count, cookies: [{name, domain, path, expires, secure, httpOnly}]}
    """
    session = BrowserSession.get()
    await session._ensure_connected()
    cookies = await session._context.cookies()
    if url_pattern:
        cookies = [c for c in cookies if url_pattern in c.get("domain", "")]
    safe = [
        {
            "name": c["name"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "expires": c.get("expires"),
            "secure": c.get("secure"),
            "httpOnly": c.get("httpOnly"),
        }
        for c in cookies
    ]
    return {"count": len(safe), "cookies": safe}


async def health() -> dict[str, Any]:
    """检查 Chrome CDP 是否活着 + 当前 page 数."""
    import requests

    host = _chrome_host()
    port = _chrome_port()
    try:
        r = await __import__("asyncio").to_thread(
            requests.get, f"http://{host}:{port}/json/version", timeout=5
        )
        r.raise_for_status()
        info = r.json()
    except Exception as e:
        return {"healthy": False, "error": str(e)[:200], "chrome_endpoint": f"{host}:{port}"}

    page_count = 0
    try:
        session = BrowserSession.get()
        pages = await session.all_pages()
        page_count = len(pages)
    except Exception:
        pass

    return {
        "healthy": True,
        "browser": info.get("Browser", "?"),
        "user_agent": info.get("User-Agent", "?")[:120],
        "page_count": page_count,
        "chrome_endpoint": f"{host}:{port}",
    }
