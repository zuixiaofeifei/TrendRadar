# TrendRadar

> **个人 fork** · 上游 [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar)
> 之上加了:B 类 API 关键词检索 + J1 远程浏览器接管(扫码登录站) +
> 16 个 MCP 浏览器工具.
>
> 这份 README 就是部署 + 配置 + 日常使用全套手册.
> 不会用 MCP 提问?看 [README-MCP-FAQ.md](README-MCP-FAQ.md)(数据查询类工具的 Q&A 范例).

---

## 目录

- [项目能做什么](#项目能做什么)
- [架构概览](#架构概览)
- [前置准备](#前置准备)
- [部署步骤](#部署步骤)
- [配置文件详解](#配置文件详解)
- [日常运行](#日常运行)
- [自定义信息源与关键词](#自定义信息源与关键词)
- [查看数据](#查看数据)
- [MCP 接入(42 工具,Claude Code / Cherry Studio 等)](#mcp-接入)
- [J1 远程浏览器接管(扫码登录站点)](#j1-远程浏览器接管)
- [常见操作](#常见操作)
- [故障排查](#故障排查)
- [已知限制](#已知限制)
- [路线图](#路线图)

---

## 项目能做什么

**一句话**:订阅 + 跨源关键词检索 + 远程浏览器接管, 抓 AI/科技/创业方向内容,代码清洗 → AI 筛选打分 → 飞书推送 / MCP 自然语言查询 / 任意 AI Agent 实时操控浏览器抓 J1 类登录态站点。

**具体能力**:

| 能力 | 说明 |
|------|------|
| RSS 订阅 | 各种官方原生 RSS、博客、播客 RSS |
| Reddit 子版块 RSS | 不需要 OAuth,r/LocalLLaMA 等直接订阅 |
| 关键词跨源检索 | 给关键词 → 同时去 GitHub Search / HN Algolia / Reddit OAuth 检索 |
| **远程浏览器接管(J1)** | 服务器跑真 Chrome + 持久登录态,AI 手机扫码一次永久复用,任意站点都能抓 |
| AI 智能筛选 | 用自然语言描述你的兴趣,AI 给每条打分(0~1) |
| AI 摘要打标签 | 单条 DeepSeek 处理,输出摘要+标签+评分 |
| 多渠道推送 | 飞书 / 钉钉 / 企微 / TG / 邮件 / ntfy / Bark / Slack / Webhook |
| HTML 报告 | 浏览器可看,有暗色模式 / 搜索 / 复制等 |
| 调度 | 时段化:早晚汇总 / 工作时段 / 自定义 |
| MCP Server | **42 个工具**(26 数据 + 16 浏览器),Claude Code / Cursor / Cherry Studio 自然语言操作 |

**不会做的事**(显式排除):
- 国内 11 个全民热榜聚合(可关掉)
- L2 五板块舆情分析(可关掉)
- AI 翻译(可关掉)

---

## 架构概览

```
                ┌─────────── AI 客户端 (Claude Code / Cursor) ────────────┐
                │                MCP over SSH stdio                       │
                └────────────────────┬────────────────────────────────────┘
                                     ↓
┌────────────────────── docker 网络 ─────────────────────────────────────┐
│                                                                          │
│   ┌──────────────────┐    ┌──────────────────────┐    ┌───────────────┐ │
│   │  trendradar      │    │  trendradar-mcp      │    │ trendradar-   │ │
│   │  (cron 抓取主体)  │    │  (FastMCP, 42 tools) │ ←→ │ chrome (Chrome│ │
│   │                  │    │  - 26 数据查询       │    │ +Xvfb+nginx)  │ │
│   │  - 国内热榜       │    │  - 16 浏览器接管 ⭐  │    │ chrome-data   │ │
│   │  - RSS 订阅       │    │                      │    │ volume 持久   │ │
│   │  - keyword 检索   │    └──────────────────────┘    │ 登录态        │ │
│   │  - AI 筛选 + 推送 │                                └───────────────┘ │
│   │  - 8080 公网托管  │                                                  │
│   └──────────────────┘                                                  │
└────────────────────────────────────────────────────────────────────────┘
                                ↓
                  飞书 / output/qr/*.png (手机扫码)

数据流向:
  数据源 (R1/R2/B/J1) → 归一化 → SQLite → AI 筛选 → 推送/查询/Agent 操控
```

### 数据源分类

| 类 | 来源 | 鉴权 | 入口 |
|---|------|------|------|
| **R1** | 官方 RSS(HN/博客/Reddit 子版块等) | 无 | `rss.feeds` |
| **R2** | RSSHub 中转(微博/B站/即刻) | 自建 | `rss.feeds`(把 RSSHub 地址写进来) |
| **B** | 官方搜索 API(GitHub/HN/Reddit OAuth) | 部分需 | `keyword_search.sources` |
| **J1** ⭐ | 远程浏览器接管(小红书/即刻/知乎/X 等登录态站) | 手机扫码一次 | AI Agent 用 `browser_*` MCP 工具实时调度 |

### 关键路径(代码视角)

```
trendradar/__main__.py::NewsAnalyzer.run()
  ├─ _crawl_data            国内热榜(可关)
  ├─ _crawl_rss_data        RSS 抓取 + 内部调 _run_keyword_search
  │     ↓
  │   _run_keyword_search → SearchRouter.run_all()
  │     → GitHub/HN/Reddit fetcher 并发 → 合并去重 → 写虚拟 RSS feed
  │     ↓
  │   _merge_search_into_rss
  │     ↓
  │   save_rss_data         落 SQLite
  │     ↓
  │   _process_rss_data_by_mode
  └─ _execute_mode_strategy
        ↓
      AIFilter (DeepSeek 打分)
        ↓
      Notification dispatcher (飞书/...)
```

---

## 前置准备

### 服务器要求

- Linux(Ubuntu 22.04 / Debian 12 / OpenCloudOS 等均可)
- Python 3.12+
- 网络:能访问 GitHub / DeepSeek / 飞书 / Reddit / HN
- 磁盘:每天约 5~50 MB(取决于关键词/源数量),建议留 5 GB+
- 内存:512 MB+ 够用

### 凭据清单

| 项 | 用途 | 必要性 | 申请地址 |
|---|------|--------|---------|
| **DeepSeek API Key** | LLM 调用 | 必须 | https://platform.deepseek.com/api_keys |
| **飞书 webhook_url** | 推送 + J1 扫码 QR | 必须 | 飞书群 → 设置 → 群机器人(或 Lark Flow trigger) |
| **公网 IP / 域名** | 手机扫 QR 看图必须 | 用 J1 时必填 | 直接填服务器公网 IP 即可 |
| **8080 端口公网开放** | 同上 | 用 J1 时必须 | 云控制台防火墙 + 主机 iptables 都要放 |
| **GitHub PAT** | GitHub Search 限流升级 | 强烈推荐 | https://github.com/settings/tokens?type=beta |
| **Reddit OAuth** | Reddit 关键词检索 | 可选(已有 RSS 兜底) | https://developers.reddit.com → 等审核 |

---

## 部署步骤

### 1. clone 代码

```bash
git clone git@github.com:zuixiaofeifei/TrendRadar.git
cd TrendRadar
```

### 2. 安装依赖

```bash
# 推荐 uv(项目 pyproject.toml 已配)
pip install uv
uv sync

# 或者纯 pip
pip install -r requirements.txt
```

### 3. 配置密钥(docker/.env)

docker 部署:所有密钥写在 `docker/.env`,docker compose 自动注入容器:

```bash
vim docker/.env
```

**最小可跑字段**:

```bash
# AI
AI_API_KEY=sk-你的DeepSeek key
AI_MODEL=deepseek/deepseek-v4-flash

# 飞书 (支持多账号,分号分隔,任一收到即算成功)
# 自动识别 Lark Flow (www.feishu.cn) vs 标准机器人 (open.feishu.cn)
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx

# 关键词跨源检索
GITHUB_SEARCH_TOKEN=github_pat_xxxx   # 留空也能跑,只是 60/h 限流

# J1 浏览器接管 (留空就不启用 J1)
PUBLIC_HOST=150.158.98.191            # 你服务器公网 IP,手机扫 QR 用
# CHROME_HOST/CHROME_PORT 不用改, docker compose 默认值 trendradar-chrome:9222

# 运行
RUN_MODE=cron
CRON_SCHEDULE=*/30 * * * *
IMMEDIATE_RUN=true
```

**字段完整对照表**见 [.env ↔ config.yaml 字段对照](#env-字段对照)。

收紧权限:

```bash
chmod 600 docker/.env
```

非 docker 部署(裸 Python):上面字段全部用 `export` 设成环境变量即可。

### 4. 打开 keyword_search 总开关

```bash
vim config/config.yaml
```

定位 `keyword_search` 段:

```yaml
keyword_search:
  enabled: true          # ← 改成 true
  keywords:              # ← 改成你关心的
    - "Claude Code"
    - "AI Agent"
    - "MCP"
    - "DeepSeek"
  time_range_days: 1
  max_results_per_source: 20
```

### 5. (推荐) 关掉国内热榜 + L2

```yaml
# config.yaml
platforms:
  enabled: false                  # 关国内热榜聚合

ai_analysis:
  enabled: false                  # 关 L2 五板块分析

display:
  regions:
    ai_analysis: false            # 推送区块也不显示
```

### 6. 跑诊断

```bash
python -m trendradar --doctor
```

预期看到全 ✓。若有 ✗,看 [故障排查](#故障排查)。

### 7. 测推送

```bash
python -m trendradar --test-notification
```

飞书群应该收到测试消息。

### 8. 真实跑一次

```bash
python -m trendradar 2>&1 | tee /tmp/trendradar-first-run.log
```

关注日志:
- `[RSS] 抓取完成: X 个源成功`
- `[Search] 跨源关键词检索启动`
- `[Search] hn:xxx → N 条`
- `[AI筛选] 总计 X 条 → 命中 Y 条`
- `[飞书] 推送成功`

### 9. 配置 cron / systemd 让它定时跑

#### 方式 A:简单 cron(每半小时跑一次)

```bash
crontab -e
```

```cron
*/30 * * * * cd /root/TrendRadar && /usr/bin/python -m trendradar >> /var/log/trendradar.log 2>&1
```

#### 方式 B:用项目自带 schedule(时段化)

```yaml
# config.yaml
schedule:
  enabled: true
  preset: "morning_evening"    # 早晚汇总(推荐)
                                # 其他:always_on / office_hours / night_owl / custom
```

然后启动**单次入口 + 外部循环**(项目本身不是常驻进程):

```bash
# 每 30 分钟跑一次,由内部 timeline.yaml 决定何时实际推送
*/30 * * * * cd /root/TrendRadar && /usr/bin/python -m trendradar
```

---

## 配置文件详解

### config.yaml(公开,可 commit)

| 段 | 关键字段 | 说明 |
|----|---------|------|
| `app.timezone` | `Asia/Shanghai` | 影响所有时间显示 |
| `schedule.enabled` | true/false | 启用时段化调度 |
| `schedule.preset` | `morning_evening`/`always_on`/... | 调度预设 |
| `platforms.enabled` | true/false | **国内热榜总开关**(推荐 false) |
| `rss.enabled` | true | RSS 总开关 |
| `rss.freshness_filter.max_age_days` | 1 | RSS 文章新鲜度天数 |
| `rss.feeds` | 数组 | RSS 源列表 |
| **`keyword_search.enabled`** | true/false | **跨源关键词检索总开关** |
| **`keyword_search.keywords`** | 字符串数组 | 你要跨源搜的关键词 |
| `keyword_search.time_range_days` | 1 | 检索时间窗口 |
| `keyword_search.sources.github.enabled` | true | GitHub 检索开关 |
| `keyword_search.sources.hackernews.enabled` | true | HN 检索开关(最稳) |
| `keyword_search.sources.reddit.enabled` | false | Reddit 检索开关(待审核) |
| `report.mode` | `current`/`daily`/`incremental` | 推送模式 |
| `filter.method` | `keyword`/`ai` | 筛选方式 |
| `ai_filter.min_score` | 0.7 | AI 筛选最低分阈值 |
| `display.regions.*` | true/false | 推送各区块开关 |
| `notification.enabled` | true | 推送总开关 |
| `ai.model` | `deepseek/deepseek-chat` | LiteLLM 模型 |
| `ai_analysis.enabled` | **false**(推荐) | L2 五板块分析 |
| `ai_translation.enabled` | true/false | AI 翻译(英文源会用到) |
| `storage.backend` | `auto`/`local`/`remote` | 存储后端 |

### .env 字段对照

`docker/.env` 通过 docker compose `environment` 段映射进容器,字段对应 `config.yaml` 路径:

| docker/.env 字段 | config.yaml 路径 |
|------------------|-----------------|
| `AI_API_KEY` | `ai.api_key` |
| `AI_MODEL` | `ai.model` |
| `AI_API_BASE` | `ai.api_base` |
| `AI_ANALYSIS_ENABLED` | `ai_analysis.enabled` |
| `FEISHU_WEBHOOK_URL` | `notification.channels.feishu.webhook_url` |
| `DINGTALK_WEBHOOK_URL` | `notification.channels.dingtalk.webhook_url` |
| `WEWORK_WEBHOOK_URL` | `notification.channels.wework.webhook_url` |
| `TELEGRAM_BOT_TOKEN` | `notification.channels.telegram.bot_token` |
| `TELEGRAM_CHAT_ID` | `notification.channels.telegram.chat_id` |
| `EMAIL_FROM` / `EMAIL_PASSWORD` / `EMAIL_TO` | `notification.channels.email.*` |
| `NTFY_TOPIC` / `NTFY_TOKEN` | `notification.channels.ntfy.*` |
| `BARK_URL` | `notification.channels.bark.url` |
| `SLACK_WEBHOOK_URL` | `notification.channels.slack.webhook_url` |
| `GENERIC_WEBHOOK_URL` | `notification.channels.generic_webhook.webhook_url` |
| `S3_ENDPOINT_URL` | `storage.remote.endpoint_url` |
| `S3_BUCKET_NAME` | `storage.remote.bucket_name` |
| `S3_ACCESS_KEY_ID` | `storage.remote.access_key_id` |
| `S3_SECRET_ACCESS_KEY` | `storage.remote.secret_access_key` |
| `S3_REGION` | `storage.remote.region` |
| **`GITHUB_SEARCH_TOKEN`** | `keyword_search.sources.github.token` |
| **`REDDIT_CLIENT_ID`** | `keyword_search.sources.reddit.client_id` |
| **`REDDIT_CLIENT_SECRET`** | `keyword_search.sources.reddit.client_secret` |
| **`REDDIT_USER_AGENT`** | `keyword_search.sources.reddit.user_agent` |
| `RUN_MODE` | (容器入口脚本读) |
| `CRON_SCHEDULE` | (容器入口脚本读) |
| `IMMEDIATE_RUN` | (容器入口脚本读) |
| `WEBSERVER_PORT` | (容器入口脚本读) |

### 优先级链

```
环境变量(docker/.env)    →    config.yaml 同字段(留作覆盖入口)
```

- 任一字段:env 非空时取 env;否则取 config.yaml 同字段
- config.yaml 在本 fork 中已**移除**所有密钥字段(全部走 env)
- 想临时不走 .env 调试?直接在 config.yaml 写值即可,代码不区分来源

### 其他配置文件

| 文件 | 作用 |
|------|------|
| `config/frequency_words.txt` | 关键词筛选词表(filter.method=keyword 时用) |
| `config/ai_interests.txt` | AI 兴趣自然语言描述(filter.method=ai 时用) |
| `config/ai_analysis_prompt.txt` | L2 分析 prompt(已关) |
| `config/ai_translation_prompt.txt` | AI 翻译 prompt |
| `config/timeline.yaml` | 调度时段表 |

---

## 日常运行

### 单次跑

```bash
cd ~/TrendRadar
python -m trendradar
```

### 看调度状态

```bash
python -m trendradar --show-schedule
```

### 测推送

```bash
python -m trendradar --test-notification
```

### 体检

```bash
python -m trendradar --doctor
```

### 内置 webserver(看 HTML 报告)

容器 entrypoint 在 `cron` 模式下会自动起 8080 端口的静态服务托管 `output/`,
直接访问即可:

```
http://<服务器IP>:8080         # latest 报告 (output/index.html)
http://<服务器IP>:8080/qr/     # QR 截图目录
```

宿主机本地也可以打开 `output/index.html` 看 (volume 映射, 自动跟容器同步).

---

## 自定义信息源与关键词

### 添加 RSS 源

`config.yaml` → `rss.feeds` 数组里加一项:

```yaml
- id: "latent-space"             # 唯一 ID,字母数字横线
  name: "Latent Space"           # 显示名
  url: "https://www.latent.space/feed"
  # 可选字段:
  # enabled: false                # 临时禁用
  # max_age_days: 7               # 覆盖全局新鲜度过滤
  # max_items: 50                 # 每次最多拉多少条
```

### 推荐 AI/科技/创业方向 RSS

```yaml
# 已加(默认开启)
- id: "hacker-news"
  url: "https://hnrss.org/frontpage"
- id: "r-LocalLLaMA"
  url: "https://www.reddit.com/r/LocalLLaMA/new.rss"
- id: "r-MachineLearning"
  url: "https://www.reddit.com/r/MachineLearning/hot.rss"
- id: "r-singularity"
  url: "https://www.reddit.com/r/singularity/hot.rss"
- id: "r-SaaS"
  url: "https://www.reddit.com/r/SaaS/new.rss"

# 建议补充(英文 AI 圈)
- id: "latent-space"
  url: "https://www.latent.space/feed"
- id: "import-ai"
  url: "https://jack-clark.net/feed/"
- id: "interconnects"
  url: "https://www.interconnects.ai/feed"
- id: "the-batch"
  url: "https://www.deeplearning.ai/the-batch/feed/"
- id: "simonw"
  url: "https://simonwillison.net/atom/everything/"
- id: "openai-blog"
  url: "https://openai.com/news/rss.xml"
- id: "anthropic-blog"
  url: "https://www.anthropic.com/news/rss.xml"

# 建议补充(中文 AI 圈)
- id: "founderpark"
  url: "https://mp.weixin.qq.com/rss?biz=MzkzMDExMzg4Nw=="   # 用 RSSHub 中转
- id: "ruanyifeng-weekly"
  url: "https://www.ruanyifeng.com/blog/atom.xml"
- id: "haiwai-unicorn"
  url: "..."                                                 # RSSHub 即刻路由
```

### 调整关键词

```yaml
keyword_search:
  keywords:
    - "Claude Code"
    - "AI Agent"
    - "MCP server"           # 词组用引号
    - "RAG"
    - "vector database"
```

**注意**:每个关键词会乘以"启用的 provider 数量"次请求。3 关键词 × 2 provider = 6 次请求。GitHub 无 token 时 60/h,自己估。

### 切换筛选策略

#### 方案 A:关键词词组(快、零 AI 成本)

```yaml
filter:
  method: "keyword"
```

编辑 `config/frequency_words.txt`(具体语法看文件注释)。

#### 方案 B:AI 兴趣描述(贵、灵活)

```yaml
filter:
  method: "ai"
ai_filter:
  min_score: 0.7              # 越高越严
  batch_size: 200             # 单次喂 AI 多少条
```

编辑 `config/ai_interests.txt`,用自然语言写你想看什么:

```
我关心 AI 创业、Claude 生态、大模型工程化的内容。
特别关注 AI Agent 框架、MCP server、LLM 应用层、AI 工具。
不感兴趣:加密币炒作、社会新闻、明星娱乐。
```

---

## 查看数据

### SQLite 数据库

```bash
# 当天数据库位置
ls output/

# 看一下表结构
sqlite3 output/$(date +%F).db ".schema"

# 看 RSS 条目总数(按源分组)
sqlite3 output/$(date +%F).db "SELECT feed_id, COUNT(*) FROM rss_items GROUP BY feed_id"

# 看 search:* 虚拟 feed
sqlite3 output/$(date +%F).db "SELECT feed_id, COUNT(*) FROM rss_items WHERE feed_id LIKE 'search:%' GROUP BY feed_id"

# 查某个关键词最近 10 条
sqlite3 output/$(date +%F).db "SELECT title, url FROM rss_items WHERE title LIKE '%Claude%' ORDER BY first_time DESC LIMIT 10"
```

### HTML 报告

```bash
# 文件位置 (宿主机直接看, output 是 docker volume)
ls output/*.html
open output/index.html

# 或浏览器访问已自动启动的 webserver
# http://<服务器IP>:8080
```

### 飞书推送

按 `schedule` 设的时段推送,典型预设:

| 预设 | 推送时点 |
|------|---------|
| `always_on` | 全天有新增就推 |
| `morning_evening` | 早晚两次汇总 |
| `office_hours` | 工作日 9 / 12 / 18 三次 |
| `night_owl` | 午后速览 + 深夜全天汇总 |

---

## MCP 接入

让 Claude Code / Cursor / Cherry Studio 等 MCP 客户端**自然语言查询数据 + 实时操控浏览器**(42 个工具)。

### 服务器侧:trendradar-mcp 容器已起

docker compose 起来后, `trendradar-mcp` 容器以 HTTP 模式监听 3333,
同时支持每次连接 spawn 一个 stdio 子进程(给 Claude Code 用)。

```bash
# 验证容器健康
docker exec trendradar-mcp env | grep MCP_PORT
docker logs trendradar-mcp 2>&1 | head -100   # 看 42 个工具注册列表
```

### 在 Claude Code (Mac) 接入: SSH stdio 模式

最简单的方式 — 让 Claude Code 通过 SSH 直接调远程 docker exec:

```bash
# 1. 配 SSH 免密 (一次性)
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
ssh-copy-id root@<服务器IP>

# 2. 加 MCP server
claude mcp add trendradar \
  -- ssh -o BatchMode=yes -o StrictHostKeyChecking=no \
  root@<服务器IP> \
  docker exec -i trendradar-mcp python -m mcp_server.server --transport stdio

# 3. 重启 Claude Code 后,新 session 已能调 mcp__trendradar__*
```

### 在 Claude Desktop / Cherry Studio 接入: HTTP 模式

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trendradar": {
      "transport": "http",
      "url": "http://<服务器IP>:3333/mcp"
    }
  }
}
```

⚠️ HTTP 模式公网暴露要谨慎,生产建议加 nginx + token 认证,
或继续用 SSH stdio。

### MCP 工具(42 个)

**数据查询/分析 (26 个,原有)**:
- 查询: `get_trending_topics` / `search_news` / `search_rss` / `find_related_news`
- 文章: `read_article` / `read_articles_batch`
- 分析: `aggregate_news` / `compare_periods` / `analyze_sentiment`
- 系统: `get_system_status` / `list_available_dates`
- 通知: `send_notification`

**浏览器接管 (16 个,新增 ⭐)**:
- `browser_help` — **首次必调**,读 SKILL.md 看完整操作指南
- `browser_health` — 检查远程 Chrome 是否活
- `browser_navigate` / `browser_snapshot` / `browser_click` / `browser_fill` / `browser_evaluate`
- `browser_screenshot` / `browser_push_qr_to_feishu` — 截 QR 推飞书让你手机扫
- `browser_wait_for` / `browser_list_tabs` / `browser_find_tab` / `browser_close_tab`
- `browser_get_url` / `browser_get_html` / `browser_get_cookies`

详见 [J1 远程浏览器接管](#j1-远程浏览器接管) 章节。

**典型用法**:
- 数据查询: 问 "今天 AI Agent 领域有什么新动态" → 自动调 `search_news`
- 浏览器: "打开知乎抓我关注的人最新 10 篇" → 自动 navigate/snapshot/扫码登录(首次)/抓取
- 组合: "抓即刻最新 20 帖 + 把链接逐一打开总结成日报" → 全链路自动化

---

## J1 远程浏览器接管

**给反爬强、要登录态的站点用** — 小红书、即刻、知乎、X、B 站、微博等。
登录态服务器持久化, **你扫一次码后,任何 AI Agent 都直接已登录**。

### 架构

3 个 docker 容器协同:

```
Claude Code (Mac)
    ↓ MCP stdio
trendradar-mcp ── browser_* tools ──→ Playwright connect_over_cdp
                                              ↓
                                      trendradar-chrome
                                       (真 Chrome + Xvfb + nginx)
                                              ↓
                                       --user-data-dir=/data
                                       (chrome-data volume 持久化)
```

为什么要 nginx 反代?Chrome 111+ 强制只绑 localhost + 严格校验 HTTP `Host` 头,
nginx 在中间改写 Host 让跨容器调用通,顺带支持 WebSocket(CDP 走 WS)。

### 首次扫码登录流程

在 Claude Code 里直接说:

> "打开 web.okjike.com,如果需要登录就推 QR 到飞书让我扫"

Claude 会自己跑:
1. `browser_navigate("https://web.okjike.com/")` — 检测重定向到 `/login`
2. `browser_snapshot()` — 找到 QR 元素
3. `browser_push_qr_to_feishu("[class*=qrCodeContainer]", label="即刻")` — 飞书收到一条带 URL 的卡片
4. 你**手机点飞书消息里的链接** → 浏览器打开 QR 图 → 即刻 App 扫码
5. `browser_wait_for(登录后元素, timeout_ms=120000)` — 等扫码完成
6. cookies/localStorage 写入 `chrome-data` volume → **下次同站访问自动登录**

### 适用场景对照

| 站点 | 扫码 App | 反爬强度 | 状态 |
|---|---|---|---|
| 即刻 (web.okjike.com) | 即刻 App | 中 | ✅ 验证通过 |
| 知乎 (zhihu.com) | 知乎/微信 | 中-强 | 同范式可加 |
| 小红书 (xiaohongshu.com) | 小红书 App | **极强**(滑块+IP) | 可试,需配频率控制 + 代理 |
| 微博 (weibo.com) | 微博 App | 中 | 可加 |
| X (twitter.com) | TOTP/邮箱 | 中 | 可加(需出海代理) |
| B 站 (bilibili.com) | B 站 App | 中 | 可加 |

### 加新站点

**不用改代码**, 只要在 Claude Code 里描述目标:

> "我要抓 X 网站, 请你 navigate 看 DOM 结构, 找到登录入口和内容选择器"

Claude 用现有 16 个工具自适应探索。复用率高的站点 selector 可以补进
`mcp_server/skills/browser/SKILL.md` 让后续 session 直接知道。

### 限制

- ❌ 自动绕过验证码 (reCAPTCHA / 滑块都校验 `isTrusted`)
- ❌ 自动接收手机短信验证码 (需要 SMS 代收平台)
- ❌ 绕过 IP 风控 (需要住宅代理, $30+/月)
- ⚠️ 服务器 IDC IP 在小红书等强反爬站很快被风控,可能要降低频率到每 6 小时

### 关键调试命令

```bash
# Chrome 健康
docker exec trendradar-mcp python -c "
import asyncio
from mcp_server.tools import browser
print(asyncio.run(browser.health()))
"

# Chrome 容器日志
docker logs trendradar-chrome --tail 30

# 看持久化的登录态文件
ls -la /root/project/TrendRadar/output/chrome-data/Default/

# 清空登录态重新扫码
docker compose -f docker-compose-build.yml stop trendradar-chrome
rm -rf output/chrome-data/*
docker compose -f docker-compose-build.yml up -d trendradar-chrome
```

---

## 常见操作

### 临时禁用某个 RSS 源(不想删)

```yaml
- id: "yahoo-finance"
  name: "雅虎财经"
  url: "..."
  enabled: false           # ← 加这行
```

### 加新通知通道(比如钉钉)

在 `docker/.env` 加:

```bash
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
```

`docker-compose.yml` 已经映射好了,直接 `docker compose up -d` 生效。

### 多账号推送(同时推到 2 个飞书群)

在 `docker/.env`(分号分隔):

```bash
FEISHU_WEBHOOK_URL=https://url1;https://url2
```

### 临时不推送(只抓数据)

```yaml
# config.yaml
notification:
  enabled: false
```

数据照常落库,可后续用 MCP 查询。

### 改报告模式

```yaml
report:
  mode: "incremental"          # 只推新增(零重复)
  # 或 current(当前榜)/daily(当日汇总)
```

### 启用代理(国内访问 GitHub/Reddit 慢)

```yaml
keyword_search:
  use_proxy: true
  proxy_url: "http://127.0.0.1:7890"
```

---

## 故障排查

### 跑 `--doctor` 报错

| 错误 | 原因 | 处理 |
|------|------|------|
| `配置文件加载失败` | yaml 语法 | `python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"` |
| `AI 模型连通失败` | DeepSeek key 错/网络 | 检查 `docker/.env` 里 `AI_API_KEY` + `curl https://api.deepseek.com/v1/models -H "Authorization: Bearer $KEY"` |
| `飞书 webhook 未配置` | `.env` 没填 `FEISHU_WEBHOOK_URL` | 检查 `docker/.env`,改完 `docker compose restart` |

### 推送收不到

```bash
# 单独测推送通路
python -m trendradar --test-notification
```

如果上面成功但正常跑不推送:
- 检查 `notification.enabled: true`
- 检查 `schedule` 当前时段是否允许推送(`--show-schedule`)
- 检查日志里有没有 `[飞书] 推送成功`

### `[Search] is_active: False`

- `keyword_search.enabled: false` → 改 true
- `keywords: []` 空 → 填关键词
- 所有 sources 都 disabled → 至少开一个

### GitHub `403: API rate limit`

- 没配 PAT 时 60/h,跑多关键词容易触发
- 处理:`docker/.env` 加 `GITHUB_SEARCH_TOKEN=github_pat_xxx`,然后 `docker compose restart`

### Reddit 403 / 401

- 公开 endpoint 已被 Reddit 封,必须 OAuth
- 状态:Reddit Developer Platform 审核中
- 兜底:用 `rss.feeds` 里的 r/* 订阅(已默认配)

### 飞书推送字数超限

- 项目已做自动分批(`advanced.batch_size.feishu: 30000` 字节)
- 如果还是溢出,减少 `report.max_news_per_keyword` 或 `keyword_search.max_results_per_source`

### Reddit 子版块 RSS 拿不到

```bash
# 测试
curl -A "TrendRadar/2.0" https://www.reddit.com/r/LocalLLaMA/new.rss
```

返回 HTTP 200 + XML 就正常。403 可能是 IP 被 Reddit 限速,换时段或加代理。

### SQLite 数据库锁住

```bash
# 看是不是有进程还在跑
ps aux | grep trendradar

# 实在锁死,杀掉再删 journal
rm output/*.db-journal
```

### 查日志

```bash
# 如果用 cron
tail -f /var/log/trendradar.log

# 直接跑
python -m trendradar 2>&1 | tee /tmp/run.log
```

---

## 已知限制

1. **Reddit OAuth 待审核**:走 RSS 兜底,已可用
2. **GitHub 60/h 限流**(无 token 时):配 PAT 解决
3. **腾讯云出海不稳**:keyword_search 调 GitHub/HN/Reddit API 可能超时,国内站不受影响
4. **首次跑较慢**:RSS 串行 + AI 单条,30 条新闻约 2-3 分钟
5. **L2 五板块分析在代码里仍存在**:用 `ai_analysis.enabled: false` 关
6. **MCP Server 没专门为 search:* feed 适配**:数据能查到,但工具描述里没明说"虚拟 feed"概念
7. **单进程,不并发**:多关键词 × 多 provider 是串行的
8. **J1 没自动 cron**:目前是 AI Agent 手动唤起,未自动定时(可在 Claude Code 里设提醒)
9. **腾讯 Lighthouse 特有: YJ-FIREWALL 拦 8080**: 需 iptables 手动 ACCEPT + cron 兜底(其他云不需要)

---

## 路线图

### 已完成 ✅

- [x] B 类 API 检索(GitHub/HN/Reddit Search) — 跨源关键词检索打通
- [x] Reddit RSS 兜底 — 不依赖 OAuth 也能拿 Reddit 内容
- [x] **J1 远程浏览器接管** — Chrome+Xvfb+nginx 容器化, 16 个 browser_* MCP 工具
- [x] **扫码登录 + 飞书 QR 推送** — 服务器持久化登录态, 一次扫码长期复用
- [x] **MCP 42 工具** + SSH stdio 接入 Claude Code
- [x] 多飞书 webhook 容错 + Lark Flow / 标准机器人自动适配

### 短期

- [ ] 补全 AI/科技方向 RSS 源池(latent.space / interconnects 等)
- [ ] 配置 timeline.yaml 调度
- [ ] J1 已知站点 selector 沉淀进 SKILL.md(知乎/小红书等)

### 中期

- [ ] F 类聚合 API 支持(Exa/Tavily/Firecrawl)
- [ ] SearchRouter 并发优化
- [ ] AIFilter 二次过滤搜索结果
- [ ] J1 cron 化 — DeepSeek 跑 agent loop 周期自动抓取(月成本几毛)

### 长期

- [ ] 自建 RSSHub 实例(走 R2 类,微博/B站/即刻)
- [ ] Web UI 配置编辑器(上游已有,fork 同步)
- [ ] 多用户隔离(目前是单人自部署)

---

## 快速参考

### 一行启动

```bash
cd ~/TrendRadar && python -m trendradar --doctor && python -m trendradar
```

### 一行修改关键词

```bash
sed -i 's/- "Claude Code"/- "Claude Code"\n    - "新关键词"/' config/config.yaml
```

### 一行查今天命中数

```bash
sqlite3 output/$(date +%F).db "SELECT feed_id, COUNT(*) FROM rss_items WHERE first_time LIKE '$(date +%H):%' GROUP BY feed_id ORDER BY COUNT(*) DESC"
```

### 一行看 latest 报告

```bash
# 宿主机直接打开 (volume 映射)
open output/index.html

# 或浏览器访问 http://<服务器IP>:8080 (webserver 由容器 entrypoint 自动启动)
```

---

**最后更新**:跟随项目改动同步更新。如发现内容与代码不一致,以代码为准 + 提 issue。
