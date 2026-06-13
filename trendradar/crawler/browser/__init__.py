"""J1 浏览器抓取层

通过 Playwright connect_over_cdp 接管 trendradar-chrome 容器里的真 Chrome,
登录态持久化到 chrome-data volume, QR 推送给用户手机扫码.

核心组件:
    session.py  — Playwright connect 封装
    login.py    — 登录态检测 + QR 截图 + 等扫码
    notify.py   — 飞书推送 QR URL
"""
from .session import browser_page, health_check, cdp_url
from .login import LoginConfig, ensure_login, take_qr_screenshot, cleanup_old_qrs
from .notify import push_qr

__all__ = [
    "browser_page",
    "health_check",
    "cdp_url",
    "LoginConfig",
    "ensure_login",
    "take_qr_screenshot",
    "cleanup_old_qrs",
    "push_qr",
]
