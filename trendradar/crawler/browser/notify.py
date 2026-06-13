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


def push_qr(site_id: str, qr_path: Path, *, expire_minutes: int = 3) -> bool:
    """推送 QR URL 到飞书, 要求用户在 expire_minutes 内扫码

    Returns:
        推送成功 True, 推送失败 False
    """
    import requests

    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "").split(";")[0].strip()
    if not webhook_url:
        logger.error("FEISHU_WEBHOOK_URL 未配置, 无法推 QR")
        return False

    url = _public_qr_url(qr_path)
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"🔐 {site_id} 扫码登录",
                    "content": [
                        [
                            {"tag": "text", "text": f"⏱ {expire_minutes} 分钟内有效\n\n"},
                            {"tag": "a", "text": "→ 点这里打开二维码", "href": url},
                            {
                                "tag": "text",
                                "text": "\n\n用站点对应的 App 扫码,\n登录态自动持久化到下一次抓取",
                            },
                        ]
                    ],
                }
            }
        },
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
        resp = r.json()
        # 飞书自定义机器人成功返回 {"code": 0, ...} 或 {"StatusCode": 0, ...}
        if resp.get("code") == 0 or resp.get("StatusCode") == 0:
            logger.info(f"[{site_id}] QR 推飞书成功: {url}")
            return True
        logger.error(f"[{site_id}] 飞书返回异常: {resp}")
        return False
    except Exception as e:
        logger.error(f"[{site_id}] 推飞书失败: {e}")
        return False
