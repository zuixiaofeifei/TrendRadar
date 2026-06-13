"""把 QR URL 推到飞书 — 用户在手机点链接看图扫码

复用 trendradar 已有的 8080 端口 (`/app/output/` 静态托管), QR 图片自动
通过 http://<server-ip>:8080/qr/xxx.png 可访问. 不需要单独 QR server.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _public_qr_url(qr_path: Path) -> str:
    """从本地路径推导公网 URL

    /app/output/qr/jike-1234.png  →  http://<PUBLIC_HOST>:<WEBSERVER_PORT>/qr/jike-1234.png
    """
    public_host = os.getenv("PUBLIC_HOST", "").strip()
    if not public_host:
        logger.warning("PUBLIC_HOST 未配置, QR URL 用 localhost (你手机扫不到)")
        public_host = "localhost"

    port = os.getenv("WEBSERVER_PORT", "8080")
    rel = qr_path.relative_to("/app/output").as_posix()
    return f"http://{public_host}:{port}/{quote(rel)}"


def _build_feishu_payload(webhook_url: str, site_id: str, public_url: str, expire_minutes: int) -> dict:
    """根据 webhook 域名生成对应格式的 payload."""
    if "www.feishu.cn" in webhook_url:
        # Lark Flow webhook: 纯文本
        text = (
            f"🔐 {site_id} 扫码登录\n"
            f"\n"
            f"⏱ {expire_minutes} 分钟内有效\n"
            f"\n"
            f"二维码: {public_url}\n"
            f"\n"
            f"用对应 App 扫码完成登录,\n"
            f"登录态自动持久化到下一次抓取"
        )
        return {"msg_type": "text", "content": {"text": text}}
    # 标准自定义机器人: 交互卡片 2.0 (markdown)
    md = (
        f"**🔐 {site_id} 扫码登录**\n\n"
        f"⏱ {expire_minutes} 分钟内有效\n\n"
        f"[→ 点这里打开二维码]({public_url})\n\n"
        f"用对应 App 扫码完成登录,\n"
        f"登录态自动持久化到下一次抓取"
    )
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "body": {"elements": [{"tag": "markdown", "content": md}]},
        },
    }


def push_qr(site_id: str, qr_path: Path, *, expire_minutes: int = 3) -> bool:
    """推送 QR URL 到飞书所有配置的 webhook (任一成功即算成功).

    FEISHU_WEBHOOK_URL 可以是分号分隔的多个 URL (多账号), 我们逐个推,
    任何一个真正送达就返回 True. 这样能容忍其中一个 Flow 配置错误.

    根据 webhook 域名走不同 payload 格式:
        - www.feishu.cn (Lark Flow): msg_type=text, 纯文本
        - open.feishu.cn (标准自定义机器人): msg_type=interactive, 卡片 2.0
    """
    import requests

    raw = os.getenv("FEISHU_WEBHOOK_URL", "")
    webhook_urls = [u.strip() for u in raw.split(";") if u.strip()]
    if not webhook_urls:
        logger.error("FEISHU_WEBHOOK_URL 未配置, 无法推 QR")
        return False

    public_url = _public_qr_url(qr_path)
    any_success = False

    for i, webhook_url in enumerate(webhook_urls, 1):
        payload = _build_feishu_payload(webhook_url, site_id, public_url, expire_minutes)
        try:
            r = requests.post(webhook_url, json=payload, timeout=10)
            r.raise_for_status()
            resp = r.json()
            if resp.get("code") == 0 or resp.get("StatusCode") == 0:
                logger.info(f"[{site_id}] 账号{i} 推飞书 API 成功: {public_url}")
                any_success = True
            else:
                logger.error(f"[{site_id}] 账号{i} 飞书返回异常: {resp}")
        except Exception as e:
            logger.error(f"[{site_id}] 账号{i} 推飞书失败: {e}")

    return any_success
