"""W1 多站点诊断:看哪些站点 Chrome 在服务器上能稳定打开

按"国内 -> 海外低风控 -> 海外高风控"顺序试,每个 site 都打印耗时,
最终给出"基础栈是否 OK"和"出海网络是否 OK"两个独立结论。
"""
import time
from playwright.sync_api import sync_playwright


SITES = [
    # (名字, URL, 选择器, 期望文案片段)
    ("Baidu (国内基线)",   "https://www.baidu.com",          "title", "百度"),
    ("GitHub Trending",     "https://github.com/trending",    "h2",    "Trending"),
    ("Hacker News",         "https://news.ycombinator.com",   "title", "Hacker News"),
    ("Reddit (公开)",       "https://www.reddit.com/r/LocalLLaMA/.json", "body", ""),
]


def main():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.set_default_timeout(20000)

        for name, url, sel, expect in SITES:
            print(f"\n→ {name}: {url}")
            t0 = time.time()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                dt = time.time() - t0
                title = page.title()
                snippet = ""
                try:
                    el = page.locator(sel).first
                    snippet = (el.text_content() or "")[:60].strip()
                except Exception:
                    snippet = "(选择器无内容)"
                ok = (not expect) or (expect.lower() in (title + snippet).lower())
                mark = "✓" if ok else "△"
                print(f"   {mark} {dt:.1f}s   title={title!r}")
                print(f"      first_match={snippet!r}")
                results.append((name, True, dt, None))
            except Exception as e:
                dt = time.time() - t0
                err = f"{type(e).__name__}: {str(e).splitlines()[0]}"
                print(f"   ✗ {dt:.1f}s   {err}")
                results.append((name, False, dt, err))

        page.close()
        browser.close()

    # ── 总结 ──
    print("\n" + "=" * 60)
    domestic_ok = any(ok for n, ok, _, _ in results if "国内" in n)
    overseas_results = [(n, ok, dt) for n, ok, dt, _ in results if "国内" not in n]
    overseas_ok = sum(1 for _, ok, _ in overseas_results if ok)

    print("结论:")
    print(f"  基础栈 (Chrome+Playwright+CDP):  {'✅ OK' if domestic_ok else '✗ 挂'}")
    print(f"  出海网络 (海外站可达):           {'✅' if overseas_ok else '✗'} {overseas_ok}/{len(overseas_results)} 站点可达")
    print("=" * 60)

    if not domestic_ok:
        return 1
    if overseas_ok == 0:
        print("\n⚠ 出海全挂 — W2 需要给 Chrome 配代理 (或走 SS/clash)")
        return 2
    if overseas_ok < len(overseas_results):
        print("\n⚠ 部分海外站不稳 — W2 阶段视情况配代理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
