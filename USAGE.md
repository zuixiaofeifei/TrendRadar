# TrendRadar 使用手册(本 fork)

> 这份文档是这个 fork 的「部署 + 配置 + 日常使用」操作手册。
> 想了解上游项目背景请看 [README.md](README.md);本文档只覆盖你实际要做的事。

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
- [MCP 接入(让 Claude/Cherry Studio 自然语言查询)](#mcp-接入)
- [常见操作](#常见操作)
- [故障排查](#故障排查)
- [已知限制](#已知限制)
- [路线图](#路线图)

---

## 项目能做什么

**一句话**:订阅 + 跨源关键词检索 AI/科技/创业方向内容,代码清洗 → AI 筛选打分 → 飞书推送 / 飞书机器人查询。

**具体能力**:

| 能力 | 说明 |
|------|------|
| RSS 订阅 | 各种官方原生 RSS、博客、播客 RSS |
| Reddit 子版块 RSS | 不需要 OAuth,r/LocalLLaMA 等直接订阅 |
| 关键词跨源检索 | 给关键词 → 同时去 GitHub Search / HN Algolia / Reddit OAuth 检索 |
| AI 智能筛选 | 用自然语言描述你的兴趣,AI 给每条打分(0~1) |
| AI 摘要打标签 | 单条 DeepSeek 处理,输出摘要+标签+评分 |
| 多渠道推送 | 飞书 / 钉钉 / 企微 / TG / 邮件 / ntfy / Bark / Slack / Webhook |
| HTML 报告 | 浏览器可看,有暗色模式 / 搜索 / 复制等 |
| 调度 | 时段化:早晚汇总 / 工作时段 / 自定义 |
| MCP Server | 21 个工具,可以让 Claude/Cherry Studio 自然语言查信息库 |

**不会做的事**(显式排除):
- 国内 11 个全民热榜聚合(可关掉)
- L2 五板块舆情分析(可关掉)
- AI 翻译(可关掉)

---

## 架构概览

```
数据源 (R1/R2/B)
   ↓
归一化 → SQLite 落库
   ↓
代码处理 (清洗 / 去重 / 规则打分)
   ↓
AI 筛选 (DeepSeek 关键词/兴趣描述 → 标签 + 评分)
   ↓
推送 (飞书 / 多通道) + HTML 报告
   ↓
MCP 查询 (Claude/Cherry Studio 自然语言访问历史数据)
```

### 数据源分类

| 类 | 来源 | 鉴权 | 入口 |
|---|------|------|------|
| **R1** | 官方 RSS(HN/博客/Reddit 子版块等) | 无 | `rss.feeds` |
| **R2** | RSSHub 中转(微博/B站/即刻) | 自建 | `rss.feeds`(把 RSSHub 地址写进来) |
| **B** | 官方搜索 API(GitHub/HN/Reddit OAuth) | 部分需 | `keyword_search.sources` |

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
| **飞书 webhook_url** | 推送 | 必须 | 飞书群 → 设置 → 群机器人 → 自定义机器人 |
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

### 3. 准备 secrets.yaml

```bash
cp config/secrets.example.yaml config/secrets.yaml
vim config/secrets.yaml
```

**最小可跑配置**:

```yaml
ai:
  api_key: "sk-你的DeepSeek key"

notification:
  channels:
    feishu:
      webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"

keyword_search:
  sources:
    github:
      token: "github_pat_xxxx"   # 留空也能跑,只是 60/h 限流
```

收紧权限:

```bash
chmod 600 config/secrets.yaml
```

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

### secrets.yaml(私密,git ignored)

**完全跟 config.yaml 字段集互斥**,只放密钥/凭据:

```yaml
ai:
  api_key: "..."

notification:
  channels:
    feishu:
      webhook_url: "..."
    # 其他通道按需填

keyword_search:
  sources:
    github:
      token: "..."
    reddit:
      client_id: "..."
      client_secret: "..."
      user_agent: "..."

storage:
  remote:
    endpoint_url: "..."
    bucket_name: "..."
    access_key_id: "..."
    secret_access_key: "..."
```

### 优先级链

```
secrets.yaml 字段非空    →    config.yaml 同字段    →    环境变量(部分字段)
```

- secrets.yaml 中**空字符串/null** 视为"未设置",不会清空 config.yaml 同名字段
- 环境变量:`AI_API_KEY` / `FEISHU_WEBHOOK_URL` / `GITHUB_SEARCH_TOKEN` / `REDDIT_CLIENT_ID` 等

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

```bash
# 启动
python manage.py start_webserver

# 访问 http://服务器IP:8080
```

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
# 文件位置
ls output/*.html

# scp 回本地浏览器看
scp root@<服务器>:~/TrendRadar/output/*.html ./

# 或在服务器起 webserver
python manage.py start_webserver
# 访问 http://服务器IP:8080
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

让 Claude / Cherry Studio / VS Code Copilot 等支持 MCP 的客户端自然语言查询你的信息库。

### 启动 MCP server

```bash
# 项目自带 entry point
trendradar-mcp

# 或
python -m mcp_server
```

监听端口默认 3333(改 `mcp_server` 配置)。

### 在 Claude Desktop 接入

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trendradar": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/TrendRadar"
    }
  }
}
```

### MCP 工具(21 个)

主要分类:
- 数据查询:`get_trending_topics` / `search_news` / `search_rss` / `find_related_news`
- 文章读取:`read_article` / `read_articles_batch`
- 聚合分析:`aggregate_news` / `compare_periods`
- 系统:`get_system_status` / `list_available_dates`
- 通知:`send_notification`(直接从对话推送到飞书)

**典型用法**:在 Claude 里直接问 "今天 AI Agent 领域有什么新动态" → Claude 调 `search_news` → 返回 + 总结。

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

在 `secrets.yaml` 加:

```yaml
notification:
  channels:
    dingtalk:
      webhook_url: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
```

不需要改 config.yaml。

### 多账号推送(同时推到 2 个飞书群)

```yaml
notification:
  channels:
    feishu:
      webhook_url: "https://url1;https://url2"    # 分号分隔
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
| `AI 模型连通失败` | DeepSeek key 错/网络 | 检查 secrets.yaml + `curl https://api.deepseek.com/v1/models -H "Authorization: Bearer $KEY"` |
| `飞书 webhook 未配置` | secrets.yaml 没填 | 看 `config.notification.channels.feishu` |

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
- 处理:secrets.yaml 填 `keyword_search.sources.github.token`

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
3. **首次跑较慢**:RSS 串行 + AI 单条,30 条新闻约 2-3 分钟
4. **L2 五板块分析在代码里仍存在**:用 `ai_analysis.enabled: false` 关
5. **MCP Server 没专门为 search:* feed 适配**:数据能查到,但工具描述里没明说有"虚拟 feed"概念
6. **单进程,不并发**:多关键词 × 多 provider 是串行的,可优化但未做

---

## 路线图

### 短期(等 Reddit 审核期间)

- [ ] 补全 AI/科技方向 RSS 源池(latent.space / interconnects 等)
- [ ] 关掉国内热榜 + L2 分析(配置即可,推荐做)
- [ ] 配置 timeline.yaml 调度

### 中期

- [ ] J1 Kimi WebBridge 集成(小红书/X/LinkedIn 等登录态源)
- [ ] F 类聚合 API 支持(Exa/Tavily/Firecrawl)
- [ ] SearchRouter 并发优化
- [ ] AIFilter 二次过滤搜索结果

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

### 一行起 webserver

```bash
python manage.py start_webserver
```

---

**最后更新**:跟随项目改动同步更新。如发现内容与代码不一致,以代码为准 + 提 issue。
