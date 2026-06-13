"""登录态检测 + QR 二维码截图 + 等扫码

每个站点提供一个 LoginConfig (登录页 URL / 检测函数 / QR 选择器),
ensure_login 自动跑完"检测 → 截 QR → 推飞书 → 等扫码 → 确认"全流程.

QR 图片存到 /app/output/qr/, 因为 trendradar 已经在 8080 端口
托管 /app/output/, 所以图片自动通过 http://<server>:8080/qr/xxx.png 可访问.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

QR_OUTPUT_DIR = Path("/app/output/qr")


@dataclass
class LoginConfig:
    """每个站点的登录配置 — 把"怎么检测/截 QR/确认"塞进同一个对象"""

    site_id: str
    """唯一标识, 如 'jike'. 用于命名 QR 文件和飞书消息标题"""

    login_url: str
    """登录页 URL"""

    is_logged_in: Callable[[object], bool]
    """检测 page 是否已登录 (避免重复弹 QR)"""

    qr_selector: str
    """QR 元素的 CSS 选择器, 必须是单个 <img> 或 <canvas>"""

    login_success_check: Callable[[object], bool]
    """扫码后判断是否登录成功 — 通常和 is_logged_in 一致"""


def take_qr_screenshot(page, qr_selector: str, site_id: str) -> Path:
    """精准截 QR 元素 (不截整页) → /app/output/qr/{site_id}-{ts}.png"""
    QR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    out_path = QR_OUTPUT_DIR / f"{site_id}-{ts}.png"

    page.wait_for_selector(qr_selector, timeout=10000)
    page.locator(qr_selector).first.screenshot(path=str(out_path))
    logger.info(f"[{site_id}] QR 截图: {out_path}")
    return out_path


def cleanup_old_qrs(keep_minutes: int = 10) -> int:
    """清理超过 keep_minutes 的 QR 图, 避免 output/qr 越长越大"""
    if not QR_OUTPUT_DIR.exists():
        return 0
    cutoff = time.time() - keep_minutes * 60
    removed = 0
    for f in QR_OUTPUT_DIR.glob("*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            pass
    if removed:
        logger.info(f"清理过期 QR: {removed} 张")
    return removed


def wait_for_login(
    page,
    success_check: Callable[[object], bool],
    timeout_seconds: int = 180,
    poll_interval: int = 3,
) -> bool:
    """轮询等扫码完成, 每 poll_interval 秒检查一次, 总超时 timeout_seconds"""
    deadline = time.time() + timeout_seconds
    last_log = 0.0
    while time.time() < deadline:
        try:
            if success_check(page):
                return True
        except Exception as e:
            logger.debug(f"轮询登录态出错 (忽略): {e}")
        # 每 30s 打一行日志
        if time.time() - last_log > 30:
            remaining = int(deadline - time.time())
            logger.info(f"等扫码中, 剩 {remaining}s ...")
            last_log = time.time()
        time.sleep(poll_interval)
    return False


def ensure_login(
    page,
    cfg: LoginConfig,
    notify_fn: Callable[[str, Path], bool],
    timeout_seconds: int = 180,
) -> bool:
    """登录态检查 + 未登录时推 QR + 等扫码

    Args:
        page: 已打开任意页面的 page 对象
        cfg: 站点登录配置
        notify_fn: 推送函数 (site_id, qr_image_path) -> success
        timeout_seconds: 扫码总超时

    Returns:
        登录成功返回 True, 超时返回 False (本轮跳过)
    """
    if cfg.is_logged_in(page):
        logger.info(f"[{cfg.site_id}] 已登录, 跳过扫码")
        return True

    logger.info(f"[{cfg.site_id}] 未登录, 打开登录页 {cfg.login_url}")
    page.goto(cfg.login_url, wait_until="domcontentloaded")

    try:
        qr_path = take_qr_screenshot(page, cfg.qr_selector, cfg.site_id)
    except Exception as e:
        logger.error(f"[{cfg.site_id}] QR 截图失败: {e}")
        return False

    if not notify_fn(cfg.site_id, qr_path):
        logger.error(f"[{cfg.site_id}] QR 推送失败, 跳过本轮")
        return False

    logger.info(f"[{cfg.site_id}] 等待扫码 (最多 {timeout_seconds}s)")
    success = wait_for_login(page, cfg.login_success_check, timeout_seconds)

    if success:
        logger.info(f"[{cfg.site_id}] 登录成功, cookies 已写入 chrome-data")
        cleanup_old_qrs()
    else:
        logger.warning(f"[{cfg.site_id}] 扫码超时, 跳过本轮抓取")
    return success
