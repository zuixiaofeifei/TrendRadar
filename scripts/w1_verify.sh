#!/bin/bash
# ============================================================
# W1 验证脚本 - Chrome + Xvfb + Playwright 链路冒烟测试
#
# 作用: 用最小代价 (~15 分钟,占 600MB 内存) 验证 J1 浏览器抓取
#       的整个底层能不能跑通,跑通才进入 W2 (登录态 + 飞书 QR)
#
# 用法: scp 到服务器后 bash w1_verify.sh
#       全程非交互,跑完输出最终结果
# ============================================================

set -e
trap 'echo ""; echo "✗ 脚本意外退出,看上面最后一步报错" >&2' ERR

LOG_DIR=/tmp/w1-verify
mkdir -p "$LOG_DIR"

section() { echo ""; echo "──────── $* ────────"; }
ok()      { echo "  ✓ $*"; }
warn()    { echo "  ⚠ $*" >&2; }
fail()    { echo "  ✗ $*" >&2; exit 1; }

# -------- 0. 检查 RAM --------
section "Step 0 / 检查内存"
free -m | head -2
AVAIL_MEM=$(free -m | awk 'NR==2{print $7}')
echo "  可用内存: ${AVAIL_MEM}MB"
if [ "$AVAIL_MEM" -lt 500 ]; then
    fail "可用内存不足 500MB,Chrome 启动会 OOM。先停掉非必要 docker / 加 swap"
fi
ok "内存够用"

# -------- 1. 装 Chrome --------
section "Step 1 / 安装 google-chrome-stable"
if command -v google-chrome-stable &>/dev/null; then
    ok "已安装: $(google-chrome-stable --version)"
else
    echo "  添加 Google Chrome 官方源..."
    cat > /etc/yum.repos.d/google-chrome.repo <<EOF
[google-chrome]
name=google-chrome
baseurl=https://dl.google.com/linux/chrome/rpm/stable/x86_64
enabled=1
gpgcheck=1
gpgkey=https://dl.google.com/linux/linux_signing_key.pub
EOF
    if ! yum install -y google-chrome-stable 2>&1 | tail -5; then
        fail "Chrome 安装失败 — 可能 dl.google.com 不通,试试用代理或下 .rpm 手动装"
    fi
    ok "安装完成: $(google-chrome-stable --version)"
fi

# -------- 2. 装 Xvfb --------
section "Step 2 / 安装 Xvfb"
if command -v Xvfb &>/dev/null; then
    ok "已安装"
else
    if ! yum install -y xorg-x11-server-Xvfb 2>&1 | tail -3; then
        fail "Xvfb 安装失败"
    fi
    ok "安装完成"
fi

# -------- 3. 启动 Xvfb --------
section "Step 3 / 启动 Xvfb (DISPLAY=:99)"
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1
nohup Xvfb :99 -screen 0 1280x720x24 > "$LOG_DIR/xvfb.log" 2>&1 &
XVFB_PID=$!
sleep 2
if ! kill -0 $XVFB_PID 2>/dev/null; then
    cat "$LOG_DIR/xvfb.log"
    fail "Xvfb 启动失败"
fi
ok "Xvfb 跑起来了 (PID=$XVFB_PID)"

# -------- 4. 启动 Chrome (CDP) --------
section "Step 4 / 启动 Chrome (CDP 端口 9222)"
pkill -f "remote-debugging-port=9222" 2>/dev/null || true
sleep 1
rm -rf /tmp/chrome-w1-test
DISPLAY=:99 nohup google-chrome-stable \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --user-data-dir=/tmp/chrome-w1-test \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    > "$LOG_DIR/chrome.log" 2>&1 &
CHROME_PID=$!
sleep 5

if ! kill -0 $CHROME_PID 2>/dev/null; then
    echo "  Chrome 启动失败,日志末尾:"
    tail -20 "$LOG_DIR/chrome.log"
    fail "Chrome 启动失败"
fi

if ! curl -sf http://127.0.0.1:9222/json/version > /tmp/chrome-version.json 2>/dev/null; then
    echo "  CDP 端口不响应,Chrome 日志:"
    tail -20 "$LOG_DIR/chrome.log"
    fail "CDP 端口 9222 不通"
fi

CHROME_VER=$(python3 -c "import json;print(json.load(open('/tmp/chrome-version.json'))['Browser'])")
ok "Chrome 跑起来了 (PID=$CHROME_PID): $CHROME_VER"

# -------- 5. 装 Playwright --------
section "Step 5 / 安装 Playwright"
if python3 -c "import playwright" 2>/dev/null; then
    ok "已安装: $(python3 -c 'import playwright;print(playwright.__version__ if hasattr(playwright,"__version__") else "OK")')"
else
    echo "  从腾讯 PyPI 镜像装..."
    if ! pip3 install --no-cache-dir -i https://mirrors.tencent.com/pypi/simple/ playwright 2>&1 | tail -5; then
        fail "Playwright 装不上 — 检查 pip3 / 网络"
    fi
    ok "安装完成"
fi

# -------- 6. 跑验证脚本 --------
section "Step 6 / 抓 Hacker News 前 5 条 (无登录)"
python3 <<'PYEOF'
import sys
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = ctx.new_page()
        print("    → 访问 https://news.ycombinator.com ...")
        page.goto("https://news.ycombinator.com", wait_until="domcontentloaded", timeout=30000)
        print(f"    ✓ 页面标题: {page.title()}")
        print("")
        print("    前 5 条头版:")
        titles = page.locator(".titleline > a").all()
        if not titles:
            print("    ⚠ 没找到标题元素,HN 改版了或被风控")
            sys.exit(2)
        for i, t in enumerate(titles[:5], 1):
            print(f"      {i}. {t.text_content()}")
        page.close()
        browser.close()
        print("")
        print("    ✓ Playwright 抓取成功")
except Exception as e:
    print(f"    ✗ 失败: {type(e).__name__}: {e}")
    sys.exit(1)
PYEOF

# -------- 7. 总结 --------
section "Step 7 / 结果"
cat <<EOF

  ═════════════════════════════════════════════
    ✅ W1 验证全部通过!
  ═════════════════════════════════════════════

  当前活着的测试进程:
    Xvfb   PID=$XVFB_PID    (端口 :99)
    Chrome PID=$CHROME_PID  (CDP 端口 9222)

  这些进程会**继续跑**,你可以再做几次 Python 测试。
  想清理: pkill -f "Xvfb :99" && pkill -f "remote-debugging-port=9222"

  日志: $LOG_DIR/
    - xvfb.log
    - chrome.log

  下一步: 把"全部通过"截图或日志贴给 Claude,然后进入 W2
          (登录态持久化 + 飞书 QR 推送)
EOF
