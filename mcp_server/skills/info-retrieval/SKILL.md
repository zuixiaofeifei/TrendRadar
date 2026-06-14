---
name: info-retrieval
description: TrendRadar 信息检索通用工作流 — 绝大多数任务的起点
---

# Info Retrieval — TrendRadar 信息获取标准工作流

本 server 是个"AI 友好的信息源调度器"，把多个抓取源（GitHub Search / Hacker News / RSS / 浏览器探测）统一抽象成 RSS 风格数据流。你的任务是用 21 个工具的组合服务用户的信息检索需求。

---

## 能力边界一图看清

```
                ┌──────────────────────────────────┐
                │       已抓数据（落 SQLite）        │
                │  - RSS 订阅 (hacker-news 等)     │
                │  - 关键词搜索 (search:github:*)   │
                └─────────────┬────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
     search_news        get_latest_rss   get_news_by_date
   (按关键词查)       (按时间查)        (查热榜历史)
            │                 │                 │
            └─────────┬───────┘                 │
                      │                         │
                      ▼                         │
                 read_article                   │
              (展开 URL → MD)                  │
                      │                         │
                      ▼                         │
                  AI 处理                        │
                      │                         │
                      ▼                         │
               send_notification ───────────────┘
                  (推用户)
```

**已抓数据之外**的场景（比如某网站没人订阅）→ 走 `browser_*` 工具探测（看 browser skill）。

---

## 5 个高频场景的标准应对

### 场景 A：用户问"X 这个概念/产品最近怎么样"

```python
# 1. 如果用户说"昨天/上周"等自然语言日期, 先解析
date = resolve_date_range("昨天")   # → {"start": "2026-06-13", "end": "2026-06-13"}

# 2. 关键词搜 — 必须 include_rss=True 否则只查热榜(热榜当前关闭)
result = search_news(
    query="Claude Code",
    include_rss=True,        # ⚠️ 关键, 默认 False
    include_url=True,        # ⚠️ 准备后续 read_article 必须 True
    date_range=date,
)

# 3. 标题不够? 展开前 3 条正文
for item in result.items[:3]:
    full = read_article(url=item.url)
    # AI 综合
```

### 场景 B：用户问"今天/最近有什么 X"

```python
# 比 search_news 便宜很多 — 直接拉时间窗口内的所有数据
result = get_latest_rss(
    days=1,                  # 最近 1 天
    include_summary=True,    # 想看摘要才传 True (省 token)
)
# AI 根据 query 主题筛选
```

**何时选 search_news vs get_latest_rss?**
- 用户问"某个具体词" → search_news
- 用户问"今天有啥" / "最近热门" → get_latest_rss

### 场景 C：search_news 没命中（覆盖范围之外的网站）

```python
# 1. 先确认确实没数据
result = search_news(query="1688 保温杯", include_rss=True)
if not result.items:
    # 2. 提示用户: 当前未配置该网站的抓取
    # 3. 建议两条路:
    #    a) 用户给 RSS URL → C 阶段的 add_rss_feed (尚未实现)
    #    b) 用户允许探测站点 → 触发 browser skill + site-adapter-create
    pass
```

### 场景 D：用户想看正文/做总结

```python
# 必须先有 URL — 所以前置 search_news 时 include_url=True
result = search_news(query="DeepSeek", include_rss=True, include_url=True)

# 并行展开多篇
for item in result.items[:5]:
    md = read_article(url=item.url, timeout=30)
    # AI 综合各篇要点
```

### 场景 E：把结果推给用户

```python
# 1. 看哪些渠道可用
channels = get_notification_channels()
# → 通常会有 feishu / telegram / email 中的一两个

# 2. 推送 (markdown 格式, server 自动适配各渠道)
send_notification(
    title="今日 AI 早报",
    message=ai_generated_markdown_summary,
    channels=["feishu"],        # 不传则全发
)
```

---

## 决策树：用户问题 → 工具选择

```
用户问题类型?
├─ "X 是什么 / 怎么样" → search_news + read_article
├─ "今天/最近有什么" → get_latest_rss
├─ "上周 X 发生了什么" → resolve_date_range + search_news
├─ "看我订阅了哪些源" → get_rss_feeds_status
├─ "帮我抓一次" → trigger_crawl
├─ "把这个发我" → send_notification
├─ "X 这个网站能查吗" → search_news 试一下, 没命中走 browser skill
└─ "改 RSS / 加订阅" → (C 阶段未实现, 引导用户用配置文件)
```

---

## 反模式 — 这些事千万不要做

### ❌ search_news 不传 include_rss=True
默认 `include_rss=False` 只查热榜。当前 `platforms.enabled=false` 热榜已关，**结果必然为空**。这是最容易踩的坑。

### ❌ read_article 没拿到 URL 就调
search_news 默认 `include_url=False` 省 token。要 read_article 必须前置 `include_url=True`。

### ❌ 把 get_news_by_date 当 RSS 历史查
`get_news_by_date` 查的是热榜 `news_items` 表，不查 RSS `rss_items`。要回查 RSS 历史用 `get_latest_rss(days=N)` 或 `search_news(date_range=...)`。

### ❌ 每个任务前都 get_rss_feeds_status
这个工具是"看健康度"用的，**不是数据查询入口**。想拿数据直接 search/get_latest。

### ❌ 把 search_news 当聊天工具反复查
单次任务调一次足够。same query 反复调浪费 token，没新数据。

### ❌ 用 trigger_crawl 当"刷新"按钮
trigger_crawl 是手动触发完整抓取流程，**耗时 30s ~ 数分钟**，不该当快速操作用。

---

## 数据时效与日期

- **系统时区**: `Asia/Shanghai`
- **当前日期**: 调 `get_system_status` 拿（不要硬编码）
- **自然语言日期**: 必先调 `resolve_date_range` 转标准格式
- **RSS freshness_filter**: 默认 1 天，超过的不推送但仍入库 — 想看更老的数据用 `days=N`

---

## 数据来源前缀识别（看 feed_id / feed_name）

| 前缀 | 含义 | 例 |
|---|---|---|
| `hacker-news` | HN 首页 RSS | `Hacker News` |
| `r-XXX` | Reddit 子版块 RSS | `r/LocalLLaMA` |
| `search:github:*` | GitHub 关键词搜索 | `GitHub: Claude Code` |
| `search:hackernews:*` | HN 关键词搜索 | `Hacker News: MCP server` |
| `search:reddit:*` | Reddit 关键词搜索 | (当前关闭等审核) |

返回数据里看到 `feed_name` 是 `"GitHub: Claude Code"` 这种 → 关键词搜索产物。
看到 `"Hacker News"`（无冒号） → 订阅式 RSS。

---

## 跨 skill 引用

- 浏览器任务（需要打开网页探测）→ `read_skill("browser")`
- 未来：site adapter 生成 → `read_skill("site-adapter")` (B 阶段)
- 未来：RSS 管理 → `read_skill("rss-management")` (C 阶段)

---

## 一句话总结

**80% 的任务流程**：`search_news(include_rss=True, include_url=True)` → `read_article` → AI 综合 → `send_notification`。其他 20% 走具体场景路径。
