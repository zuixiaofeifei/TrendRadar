#!/bin/bash
# Chrome + Xvfb + socat 启动
#
# 架构:
#   Xvfb        :99           虚拟显示器
#   Chrome      127.0.0.1:19222 (内部端口, 因 Chrome 111+ 安全策略只绑 localhost)
#   socat       0.0.0.0:9222 → 127.0.0.1:19222 (对外暴露 CDP)
#
# tini 作为 PID 1, 这个脚本管理 3 个子进程, 任意一个挂了就一起退,
# docker restart 接管重启.

set -e

INTERNAL_PORT=19222
EXTERNAL_PORT=9222

# 1. Xvfb 后台
Xvfb :99 -screen 0 1280x720x24 &
XVFB_PID=$!
sleep 2

# 2. Chrome 后台 (localhost only, 加 --remote-allow-origins 让 socat 转发后 WS 能升级)
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

# 3. 等 Chrome 起来 (最多 30s)
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$INTERNAL_PORT/json/version" >/dev/null 2>&1; then
        echo "[entrypoint] Chrome ready on internal port $INTERNAL_PORT"
        break
    fi
    sleep 1
done

# 4. socat 后台: 把容器外网 IP 上的 9222 转发到 Chrome 的 localhost:19222
socat TCP-LISTEN:$EXTERNAL_PORT,fork,reuseaddr TCP:127.0.0.1:$INTERNAL_PORT &
SOCAT_PID=$!
echo "[entrypoint] socat forwarding 0.0.0.0:$EXTERNAL_PORT -> 127.0.0.1:$INTERNAL_PORT"

# 任意子进程退出就一起退 (让 docker 重启整个容器)
wait -n $XVFB_PID $CHROME_PID $SOCAT_PID
EXIT_CODE=$?
echo "[entrypoint] 子进程退出 (code=$EXIT_CODE),停止容器..."
kill $XVFB_PID $CHROME_PID $SOCAT_PID 2>/dev/null || true
exit $EXIT_CODE
