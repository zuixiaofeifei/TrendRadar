# MCP Server Skills

LLM 工作流文档目录。**给 AI 看的，不是给人看的。**

## 跟 docstring 的区别

| Docstring | SKILL.md |
|---|---|
| 单个工具的 API 说明 | 多工具组合的工作流 |
| 写在 Python 函数里 | 独立 Markdown 文件 |
| LLM 选工具时看 | LLM 接到任务时看 |
| 例: "search_news 的参数" | 例: "用户问 X 时怎么编排工具" |

## 暴露机制

LLM 通过 `read_skill(name)` 工具拉取本目录下的 SKILL.md。  
`read_skill()` 空参数返回 skill 列表（基于每个 SKILL.md 的 frontmatter description）。

服务器启动时，`FastMCP(instructions=...)` 会给 LLM 一段 meta 提示"有 skill 系统，按需取"，
LLM 不会预加载 skill 内容（省 token），接到非平凡任务时才显式调用 `read_skill`。

## 目录结构

```
skills/
├── README.md              ← 本文件，给开发者看的
├── info-retrieval/
│   └── SKILL.md           ← 通用信息检索流程（最常用）
├── browser/
│   └── SKILL.md           ← 浏览器自动化（远程 Chrome）
├── site-adapter/          ← B 阶段加，site_adapter_create meta-tool 的工作流
│   └── SKILL.md
└── rss-management/        ← C 阶段加, add/remove RSS feed 模式
    └── SKILL.md
```

## SKILL.md 必备格式

```markdown
---
name: <slug, 跟目录名一致>
description: <一句话场景描述, 用在 read_skill() 索引>
---

# <Skill 名> — <一句话定位>

<具体内容>
```

## 写 SKILL.md 的三条原则

1. **可操作** — 每段话告诉 LLM "**遇到 X 情况就调 Y 工具**"
2. **场景导向** — 不写工具列表（docstring 已经有了），写"用户问'X'时的标准流程"
3. **反模式警告** — 写"**不要这样做**"+原因，避免 LLM 踩常见坑

## 何时该新加 skill？

满足下面任一条件考虑加：

- 一组工具有**强制使用顺序**（如 browser_navigate → snapshot → click）
- 某类任务的工作流是**可复用的模板**
- 有**领域知识**只有写文档才能传达（如 1688 反爬规则、Telegram 限速）
- 有 LLM 反复踩的**踩坑点**

不该加 skill 的情况：

- 单工具用法 → 写好 docstring 即可
- 通用编程知识 → LLM 自己会
- 一次性临时方案 → 不值得文档化

## 测试 skill 是否生效

启动 server 后：

```python
# LLM 应该自动看到 instructions 提示 "有 skill, 用 read_skill 拉"
# 然后能调:
read_skill()                      # 列出全部
read_skill("info-retrieval")      # 拉具体
read_skill("不存在的")             # 友好报错 + 提示用 read_skill()
```
