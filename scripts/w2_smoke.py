"""W2 冒烟测试 — 在 trendradar 容器内跑

验证:
  1. CHROME_HOST 环境变量正确
  2. trendradar 能 HTTP 连到 trendradar-chrome 的 9222
  3. Playwright connect_over_cdp 能接管 Chrome
  4. 能正常 navigate + 抓取 + screenshot

跑法 (容器外):
  docker exec trendradar python /app/scripts/w2_smoke.py

  或者 (本地 dev):
  CHROME_HOST=127.0.0.1 CHROME_PORT=9222 python scripts/w2_smoke.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 兼容容器内/外
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trendradar.crawler.browser import browser_page, health_check, cdp_url


def main() -> int:
    print(f"CHROME_HOST = {os.getenv('CHROME_HOST', '(default)')}")
    print(f"CDP URL     = {cdp_url()}")
    print("")

    print("→ Step 1: Chrome 健康检查")
    info = health_check()
    if not info:
        print("  ✗ Chrome CDP 不可达")
        print("  排查:")
        print("    docker compose ps                                  # 看 trendradar-chrome 是否 healthy")
        print("    docker logs trendradar-chrome | tail -20           # 看 Chrome 日志")
        print(f"    docker exec trendradar curl -s {cdp_url()}/json/version")
        return 1
    print(f"  ✓ {info.get('Browser', 'Chrome')}")
    print(f"  ✓ User-Agent: {info.get('User-Agent', '?')[:80]}...")

    print("\n→ Step 2: Playwright 接管 + 打开 baidu.com")
    with browser_page("https://www.baidu.com", timeout_ms=15000) as page:
        title = page.title()
        print(f"  ✓ 页面标题: {title!r}")
        if "百度" not in title:
            print(f"  ⚠ 标题异常,但页面打开了")

    print("\n→ Step 3: 测试截图能力 (J1 抓取必备)")
    QR_DIR = Path("/app/output/qr")
    QR_DIR.mkdir(parents=True, exist_ok=True)
    smoke_png = QR_DIR / "smoke-test.png"
    with browser_page("https://www.baidu.com") as page:
        page.screenshot(path=str(smoke_png), full_page=False)
    if smoke_png.exists() and smoke_png.stat().st_size > 1000:
        print(f"  ✓ 截图: {smoke_png} ({smoke_png.stat().st_size // 1024} KB)")
        public_host = os.getenv("PUBLIC_HOST", "<未配 PUBLIC_HOST>")
        port = os.getenv("WEBSERVER_PORT", "8080")
        print(f"  → 浏览器访问验证: http://{public_host}:{port}/qr/smoke-test.png")
    else:
        print("  ✗ 截图失败或文件过小")
        return 2

    print("\n══════════════════════════════════════════════")
    print("  ✅ W2 基础链路全部就绪")
    print("══════════════════════════════════════════════")
    print("  下一步: W2.3 写第一个站点 fetcher (默认即刻)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
