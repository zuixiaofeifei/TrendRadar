#!/bin/bash
# Chrome + Xvfb 启动脚本
# tini 接管信号, Xvfb 后台跑, Chrome 前台跑

set -e

# Xvfb 后台启动 (DISPLAY=:99)
Xvfb :99 -screen 0 1280x720x24 &
sleep 2

# Chrome 前台跑, tini 作为 PID 1 转发信号
exec google-chrome-stable \
    --remote-debugging-port=9222 \
    --remote-debugging-address=0.0.0.0 \
    --user-data-dir=/data \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --window-size=1280,720 \
    --lang=zh-CN
