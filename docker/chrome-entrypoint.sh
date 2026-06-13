#!/bin/bash
# Chrome + Xvfb + socat 启动
#
# 架构:
#   Xvfb        :99             虚拟显示器
#   Chrome      127.0.0.1:19222 (内部, Chrome 111+ 强制只绑 localhost)
#   socat       0.0.0.0:9222 → 127.0.0.1:19222 (对外暴露 CDP)
#
# tini 是 PID 1; 这个脚本管 3 个子进程, 任意一个挂了整个容器退出,
# docker restart 接管重启.
#
# 关键: 启动前先清 stale locks (Xvfb 的 .X99-lock + Chrome 的
# SingletonLock), 否则 docker restart 后会反复死锁.

set -e

INTERNAL_PORT=19222
EXTERNAL_PORT=9222

# ── 1. 清 stale locks (上一次崩溃残留) ─────────────────
cleanup_locks() {
    echo "[entrypoint] 清 stale locks"
    rm -f /tmp/.X99-lock 2>/dev/null || true
    rm -rf /tmp/.X11-unix 2>/dev/null || true
    # Chrome profile lock (在 bind mount 里, 永久残留)
    rm -f /data/SingletonLock /data/SingletonCookie /data/SingletonSocket 2>/dev/null || true
}
cleanup_locks

# ── 2. Xvfb ────────────────────────────────────────────
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 2

if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[entrypoint] ✗ Xvfb 启动失败"
    exit 1
fi
echo "[entrypoint] ✓ Xvfb (PID=$XVFB_PID)"

# ── 3. Chrome ──────────────────────────────────────────
google-chrome-stable \
    --remote-debugging-port=$INTERNAL_PORT \
    --remote-allow-origins=* \
    --user-data-dir=/data \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --window-size=1280,720 \
    --lang=zh-CN &
CHROME_PID=$!

# 等 Chrome 起来 (最多 30s), 中途崩了立即退
for i in $(seq 1 30); do
    if ! kill -0 $CHROME_PID 2>/dev/null; then
        echo "[entrypoint] ✗ Chrome 中途崩了 (PID=$CHROME_PID)"
        exit 1
    fi
    if curl -sf "http://127.0.0.1:$INTERNAL_PORT/json/version" >/dev/null 2>&1; then
        echo "[entrypoint] ✓ Chrome (PID=$CHROME_PID) ready on internal port $INTERNAL_PORT"
        break
    fi
    sleep 1
done

# ── 4. socat 转发 ──────────────────────────────────────
socat TCP-LISTEN:$EXTERNAL_PORT,fork,reuseaddr TCP:127.0.0.1:$INTERNAL_PORT &
SOCAT_PID=$!
sleep 1

if ! kill -0 $SOCAT_PID 2>/dev/null; then
    echo "[entrypoint] ✗ socat 启动失败"
    exit 1
fi
echo "[entrypoint] ✓ socat (PID=$SOCAT_PID) 0.0.0.0:$EXTERNAL_PORT -> 127.0.0.1:$INTERNAL_PORT"
echo "[entrypoint] === 所有服务就绪 ==="

# ── 5. 监督 ────────────────────────────────────────────
wait -n $XVFB_PID $CHROME_PID $SOCAT_PID
EXIT_CODE=$?
echo "[entrypoint] 子进程退出 (code=$EXIT_CODE), 停止容器..."
kill $XVFB_PID $CHROME_PID $SOCAT_PID 2>/dev/null || true
exit $EXIT_CODE
