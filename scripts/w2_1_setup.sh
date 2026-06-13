#!/bin/bash
# ============================================================
# W2.1 — 服务器持久化:Xvfb + Chrome (CDP) systemd 化
#
# 作用:让 Chrome 像系统服务一样长跑,
#   - 开机自起
#   - 崩了自动重启
#   - --user-data-dir 持久化,登录态 Cookie 永久保留
#   - 资源限制 (内存 1G),不会拖垮其他服务
#
# 跑完之后任何时候 curl http://127.0.0.1:9222/json/version
# 都能拿到 Chrome 版本号
# ============================================================

set -e
section() { echo ""; echo "──────── $* ────────"; }
ok()      { echo "  ✓ $*"; }
fail()    { echo "  ✗ $*" >&2; exit 1; }

CHROME_DATA_DIR=/var/lib/chrome-data
CDP_PORT=9222
XVFB_DISPLAY=:99
XVFB_RESOLUTION=1280x720x24

section "Step 1 / 创建持久化目录"
mkdir -p "$CHROME_DATA_DIR"
chmod 700 "$CHROME_DATA_DIR"
ok "$CHROME_DATA_DIR (chmod 700)"

section "Step 2 / 写 Xvfb systemd unit"
cat > /etc/systemd/system/xvfb.service <<EOF
[Unit]
Description=Xvfb virtual display ${XVFB_DISPLAY}
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb ${XVFB_DISPLAY} -screen 0 ${XVFB_RESOLUTION}
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
ok "/etc/systemd/system/xvfb.service"

section "Step 3 / 写 Chrome systemd unit"
cat > /etc/systemd/system/chrome-cdp.service <<EOF
[Unit]
Description=Google Chrome with CDP (port ${CDP_PORT})
After=xvfb.service
Requires=xvfb.service

[Service]
Type=simple
Environment=DISPLAY=${XVFB_DISPLAY}
ExecStart=/usr/bin/google-chrome-stable \\
    --remote-debugging-port=${CDP_PORT} \\
    --remote-debugging-address=127.0.0.1 \\
    --user-data-dir=${CHROME_DATA_DIR} \\
    --no-sandbox \\
    --disable-dev-shm-usage \\
    --disable-gpu \\
    --no-first-run \\
    --no-default-browser-check \\
    --disable-blink-features=AutomationControlled \\
    --window-size=1280,720
Restart=always
RestartSec=3
MemoryMax=1G

[Install]
WantedBy=multi-user.target
EOF
ok "/etc/systemd/system/chrome-cdp.service"

section "Step 4 / 启动 + 启用开机自起"
systemctl daemon-reload
systemctl enable xvfb.service chrome-cdp.service > /dev/null 2>&1
systemctl restart xvfb.service
sleep 2
systemctl restart chrome-cdp.service
sleep 6

section "Step 5 / 健康检查"
if ! systemctl is-active --quiet xvfb.service; then
    echo "  --- xvfb 日志 ---"
    journalctl -u xvfb.service --no-pager -n 15
    fail "xvfb.service 没起来"
fi
ok "xvfb.service: $(systemctl is-active xvfb.service)"

if ! systemctl is-active --quiet chrome-cdp.service; then
    echo "  --- chrome 日志 ---"
    journalctl -u chrome-cdp.service --no-pager -n 15
    fail "chrome-cdp.service 没起来"
fi
ok "chrome-cdp.service: $(systemctl is-active chrome-cdp.service)"

if ! curl -sf "http://127.0.0.1:${CDP_PORT}/json/version" > /tmp/cdp.json 2>/dev/null; then
    echo "  --- chrome 日志 ---"
    journalctl -u chrome-cdp.service --no-pager -n 15
    fail "CDP 端口 ${CDP_PORT} 不响应"
fi
CHROME_VER=$(python3 -c "import json;print(json.load(open('/tmp/cdp.json'))['Browser'])")
ok "CDP 响应: $CHROME_VER"

# Cookie 持久化路径确认
if [ -d "${CHROME_DATA_DIR}/Default" ]; then
    ok "Chrome 数据目录已建: ${CHROME_DATA_DIR}/Default"
fi

cat <<'EOF'

══════════════════════════════════════════════════════
  ✅ W2.1 完成 — Chrome 已 systemd 化
══════════════════════════════════════════════════════

后续操作:
  状态:    systemctl status xvfb chrome-cdp
  重启:    systemctl restart chrome-cdp
  看日志:  journalctl -u chrome-cdp -f
  CDP 测: curl -s http://127.0.0.1:9222/json/version

Chrome 数据目录: /var/lib/chrome-data
  → 登录态 cookies 持久存在,重启服务不丢
  → 服务器重启也不丢 (除非 /var/lib 被清)
EOF
