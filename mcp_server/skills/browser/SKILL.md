---
name: browser
description: 浏览器自动化工作流 — 做任何浏览器任务前必读
---

# Browser Skill — 远程 Chrome 自动化

通过 trendradar-mcp 暴露的 `browser_*` 工具接管服务器上的真 Chrome 实例。
登录态持久化在服务器端 `chrome-data` volume 里，**首次扫码后长期复用**。

## Health Check（每次开始任务前调用一次）

```python
browser_health()
# 期望 {healthy: true, browser: "Chrome/149...", page_count: N}
```

不健康时：服务器问题，停下来告诉用户检查 `trendradar-chrome` 容器。

## 核心范式

### Tabs and the current tab

所有单 tab 工具（`browser_snapshot` / `browser_click` / `browser_fill` / `browser_screenshot`）操作的是**当前 active page**。`browser_navigate` / `browser_find_tab` 切换 active。

- **新开页面共存** → `browser_navigate(url, new_tab=True)`
- **跳回已开页面** → `browser_find_tab("web.okjike.com")`（子串匹配）
- **看有几个 tab** → `browser_list_tabs()`

### @e refs 优先于 CSS

`browser_snapshot()` 返回的每个可交互元素带 `ref` 如 `e3`。后续 click/fill 用 `"@e3"` 即可：

```python
snap = browser_snapshot()
# elements: [{ref: "e1", name: "登录", tag: "button"}, ...]
browser_click("@e1")
```

**为什么**：网站 CSS 类名带 hash（如 `_qrCodeContainer_1xmcg_1`），版本一变就挂。`@e` ref 基于 DOM 顺序 + 交互角色，更稳。

降级到 CSS：snapshot 里没找到合适 ref（如 canvas/img）时，直接 CSS。

### 不要主动 evaluate 复杂代码

能用 `browser_snapshot` + `browser_click` 完成的，**不要**写 JS。仅以下情况用 `browser_evaluate`：
- 需要拿 attribute（不在 snapshot 里）
- 需要批量提取数据（如抓 50 条帖子的标题）
- 需要触发非点击事件（如 keypress）

**evaluate 必须**：
- IIFE 包裹避免污染全局：`(() => { ... return ...; })()`
- 用 `JSON.stringify` 压缩输出（不要 indent，会浪费 token）
- 返回值必须 JSON 可序列化（DOM 节点不行）

## 扫码登录流程（即刻 / 知乎 / 小红书等）

```
1. browser_navigate("https://web.okjike.com/")
   → 看返回的 url, 含 "/login" → 没登录
   → 不含 "/login" → 已登录(cookies 持久化生效), 跳到 step 5

2. browser_snapshot()
   → 看 elements 里有没有 "如何扫码" 之类按钮验证是登录页

3. browser_push_qr_to_feishu("[class*=qrCodeContainer]", label="即刻")
   → 飞书会收到一条带链接的卡片
   → 用户手机点链接看 QR 扫码登录
   → 立即告诉用户 "已推送 QR 到飞书,请 3 分钟内扫码"

4. browser_wait_for("不是登录页的特征元素", timeout_ms=180000)
   → 比如即刻登录后页面有 "推荐" tab,  用 [aria-label="推荐"] 或类似
   → 找不到登录页特征也行: browser_wait_for("[class*=qrCodeContainer]", state="hidden")

5. 登录确认后才开始抓内容
   → browser_navigate("https://web.okjike.com/timeline") (或目标路径)
   → browser_snapshot() 拿帖子卡片的 ref
   → 数据抽取 (browser_evaluate 批量 JSON.stringify)
```

**关键**：登录后第二次访问时,服务器 Chrome 会自动复用 cookies, **不会再跳 login**。如果跳了说明 cookies 过期, 重新走 step 3。

## 已知站点 selector

### 即刻 (web.okjike.com)
- 登录页 URL: `web.okjike.com/login`
- QR 容器: `[class*="qrCodeContainer"]` (152x152, 带白边好扫)
- QR canvas: `canvas[class*="qrCode"]` (纯码)
- 登录态判断: 当前 URL 不含 `/login` 即已登录

### 知乎 (zhihu.com) — TODO
### 小红书 (xiaohongshu.com) — TODO
### B 站 (bilibili.com) — TODO

(用上述工具探到后补充)

## 截图与文件输出

`browser_screenshot` 和 `browser_push_qr_to_feishu` 都把图存到 `/app/output/qr/`,
trendradar 自带的 8080 HTTP 服务会托管这个目录, 公网可访问。

**给用户看图**: 总是返回 `public_url`, 直接告诉用户去手机/浏览器打开,
不要把 base64 塞进 chat。

## Don'ts

| 行为 | 后果 |
|---|---|
| 高频点击同一元素 | 触发站点风控 |
| 同时开 > 5 个 tab | Chrome 容器 OOM (限制 1GB) |
| 抓时不加随机 sleep | 看起来机器,被风控 |
| 绕过验证码 | 不可能 (reCAPTCHA / 滑块都吃 isTrusted) |
| 在飞书消息里贴密码/token | 显然 |

## Versioning

工具版本跟 trendradar-mcp 走。任何工具调用挂出 `tool_error`,
请用户检查 `trendradar-mcp` 和 `trendradar-chrome` 两个容器状态。
